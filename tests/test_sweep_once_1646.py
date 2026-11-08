"""A queued sweep runs each step once and ends: a tier never re-enters its step, a step queues its successor once, the last step closes the sweep. #1646."""
import argparse
import json
import os
import threading
import types

import pytest

from harness import cli, gguf
from harness import heartbeat as hb
from harness import memory_store as ms
from harness import workqueue as wq
from harness.commands import discover as discover_cmd
from harness.commands import loop as loop_cmd
from harness.commands import loop_steps as steps
from harness.commands import report as report_cmd
from harness.commands import screen as screen_cmd


def _ns(**kw):
    base = {"lane": "", "top": None, "budget_gib": None, "repeat": None, "ceiling_h": 11.0,
            "effect": None, "power_budget_min": 30.0, "run": True, "loop": True, "jobs": True}
    return argparse.Namespace(**{**base, **kw})


def _inproc(argv, cwd=None, stdout=None, stderr=None, env=None):
    words = [str(w) for w in argv]
    old = os.environ.get(wq.JOB_ENV)
    os.environ[wq.JOB_ENV] = (env or {}).get(wq.JOB_ENV, "")
    try:
        rc = cli.main(words[words.index("harness.cli") + 1:])
    finally:
        if old is None:
            os.environ.pop(wq.JOB_ENV, None)
        else:
            os.environ[wq.JOB_ENV] = old
    return types.SimpleNamespace(returncode=rc)


def _work():
    t = threading.Thread(target=wq.run_pending, kwargs={"popen": _inproc, "watch": 0.02}, daemon=True)
    t.start()
    t.join(60)
    assert not t.is_alive(), "the worker never ran out of steps"


def _step_jobs() -> list[dict]:
    return [j for j in wq.jobs() if "--step" in j["argv"]]


def _name(job) -> str:
    return job["argv"][job["argv"].index("--step") + 1]


def _repend(job_id) -> None:
    """Put a finished job back in the queue, as a worker retry does."""
    conn = ms.connect()
    try:
        conn.execute("UPDATE jobs SET state = ?, finished_at = NULL, rc = NULL WHERE id = ?", (wq.PENDING, int(job_id)))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _no_job(monkeypatch):
    monkeypatch.delenv(wq.JOB_ENV, raising=False)


@pytest.fixture
def leaves(monkeypatch):
    """Every step's real body down to the tiers' own work, which is recorded instead of done."""
    got: list[str] = []

    def leaf(name, rc=0):
        def run(*args, **kw):
            got.append(name)
            return rc
        return run
    monkeypatch.setattr(discover_cmd, "_report_sweep", leaf("sweep"))
    monkeypatch.setattr(loop_cmd, "_repairs", lambda a: ((leaf("repair"), ()),))
    monkeypatch.setattr(loop_cmd, "_trial_runtimes", leaf("runtimes"))
    monkeypatch.setattr(discover_cmd, "_report_inspect", leaf("inspect", rc=1))
    monkeypatch.setattr(report_cmd, "_report_queue", leaf("queue"))
    monkeypatch.setattr(loop_cmd, "_report", lambda a, failed: 0)
    monkeypatch.setattr(loop_cmd, "_upkeep", lambda tier: got.append(steps.NAMES[[s.tier for s in steps.STEPS].index(tier)]))
    monkeypatch.setattr(loop_cmd, "_sized", lambda top, sweep: {"screens": 1, "per_s": 60.0, "why": ""})
    monkeypatch.setattr(loop_cmd, "_fetch", lambda a, plan, failed: leaf("fetch")())
    monkeypatch.setattr(gguf, "pending", lambda: False)
    monkeypatch.setattr(screen_cmd, "_report_screen", leaf("screen"))
    monkeypatch.setattr(loop_cmd, "_measure", lambda a, sweep, failed, rc=0: leaf("measure")())
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **kw: hb.beat(tier, step=1))
    monkeypatch.setattr(steps, "_settle", lambda sweep: got.append("settled"))
    return got


def _ended(leaves) -> None:
    assert leaves == [*steps.NAMES, "settled"], "a step ran more than once, or out of order"
    jobs = _step_jobs()
    assert [_name(j) for j in jobs] == list(steps.NAMES), "a step was queued more than once"
    assert wq.pending() == [] and not [j for j in wq.jobs() if j["state"] == wq.RUNNING], "the queue did not end empty"
    beat = hb.read()
    assert beat["state"] == hb.FINISHED and beat["rc"] == 1 and beat[steps.CLOSED] == beat[hb.CYCLE]
    assert beat[steps.FAILED] == ["inspect"]


def test_a_whole_sweep_runs_each_step_once_through_its_tiers_and_ends_with_the_queue_empty(leaves):
    assert steps.queue_cycle(_ns()) == 0
    _work()
    _ended(leaves)
    states = {_name(j): j["state"] for j in _step_jobs()}
    assert states["inspect"] == wq.FAILED and states["measure"] == wq.DONE


def test_a_retried_step_runs_once_and_queues_no_second_successor(leaves):
    steps.queue_cycle(_ns())
    first = wq.pending()[0]
    wq.run_one(first, popen=_inproc)
    _repend(first["id"])
    assert wq.run_one(wq.get(first["id"]), popen=_inproc)["rc"] == 0
    _work()
    _ended(leaves)


def test_a_retried_last_step_does_not_reopen_the_closed_sweep(leaves):
    steps.queue_cycle(_ns())
    _work()
    last = [j for j in _step_jobs() if _name(j) == "measure"][0]
    _repend(last["id"])
    assert wq.run_one(wq.get(last["id"]), popen=_inproc)["rc"] == 0
    _ended(leaves)


def test_a_second_copy_of_a_step_that_ran_does_nothing(leaves):
    steps.queue_cycle(_ns())
    first = wq.pending()[0]
    wq.run_one(first, popen=_inproc)
    wq.add(first["argv"], cwd=first["cwd"], requested_by="discover", resource=first["resource"])
    _work()
    assert leaves == [*steps.NAMES, "settled"]
    assert [_name(j) for j in _step_jobs()] == ["sweep", "repair", "sweep", *steps.NAMES[2:]]


def test_a_successor_already_running_or_done_is_not_queued_again():
    cycle = "1700000000"
    first = steps.queue("repair", cycle, _ns())
    for state in (wq.RUNNING, wq.DONE, wq.FAILED):
        conn = ms.connect()
        try:
            conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (state, int(first["id"])))
            conn.commit()
        finally:
            conn.close()
        again = steps.queue("repair", cycle, _ns())
        assert again["id"] == first["id"] and again["existed"], f"a {state} step was queued a second time"
    assert len(_step_jobs()) == 1


def test_a_tier_that_dispatches_back_into_the_step_is_refused_not_recursed(monkeypatch):
    entered = []

    def body(name, a, sweep, failed):
        entered.append(name)
        return steps.run_step(argparse.Namespace(**{**vars(a), "step": name, "cycle": hb.read()[hb.CYCLE]}))
    monkeypatch.setattr(steps, "_body", body)
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **kw: None)
    steps.queue_cycle(_ns())
    got = wq.run_one(wq.pending()[0], popen=_inproc)
    assert entered == ["sweep"] and got["rc"] == 1
    assert [_name(j) for j in _step_jobs()] == ["sweep", "repair"]


def test_a_step_hands_its_tiers_no_step_so_cmd_discover_runs_the_tier():
    inner = steps._inner(_ns(step="sweep", cycle="1700000000"))
    assert inner.step is None and inner.cycle is None and inner.jobs is False and inner.lane == ""
    assert json.dumps(steps.argv("sweep", "1700000000", inner)).count("--step") == 1
