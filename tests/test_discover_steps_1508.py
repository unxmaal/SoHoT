"""A sweep as queue jobs: each discovery step its own job with its own class, queuing the next; a paused measure resumes. #1508."""
import argparse
import os
import threading
import types

import pytest

from evals import watch
from harness import cli, lease, paused, sweep_guard
from harness import heartbeat as hb
from harness import memory_store as ms
from harness import workqueue as wq
from harness.commands import loop as loop_cmd
from harness.commands import loop_steps as steps
from harness.commands import measure as measure_cmd


def _ns(**kw):
    base = {"lane": "", "top": None, "budget_gib": None, "repeat": None, "ceiling_h": 11.0,
            "effect": None, "power_budget_min": 30.0, "run": True, "loop": True, "jobs": True}
    return argparse.Namespace(**{**base, **kw})


def _inproc(argv, cwd=None, stdout=None, stderr=None, env=None):
    """Run a queued `harness.cli` command in this process, with the job id the worker set."""
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


def _one(job) -> dict:
    """Claim and run one queued job in this process, as the worker would."""
    return wq.run_one(job, popen=_inproc)


def _work():
    t = threading.Thread(target=wq.run_pending, kwargs={"popen": _inproc, "watch": 0.02}, daemon=True)
    t.start()
    t.join(60)
    assert not t.is_alive(), "the worker never ran out of steps"


class Ran(list):
    starts: set


@pytest.fixture
def ran(monkeypatch):
    got = Ran()
    got.starts = set()

    def body(name, a, sweep, failed):
        got.append(name)
        got.starts.add(sweep.started)
        return 0
    monkeypatch.setattr(steps, "_body", body)
    monkeypatch.setattr(steps, "_settle", lambda sweep: got.append("settled"))
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **kw: hb.beat(tier, step=1))
    return got


def _holder():
    conn = ms.connect()
    try:
        return lease.holder(conn, loop_cmd.LEASE)
    finally:
        conn.close()


def test_each_step_runs_as_its_own_job_with_its_class_and_queues_the_next(ran):
    assert steps.queue_cycle(_ns()) == 0
    _work()
    assert ran == [*steps.NAMES, "settled"]
    assert len(ran.starts) == 1, "a step restarted the sweep ceiling"
    got = [j for j in wq.jobs() if "--step" in j["argv"]]
    assert [j["argv"][j["argv"].index("--step") + 1] for j in got] == list(steps.NAMES)
    assert [j["resource"] for j in got] == [s.resource for s in steps.STEPS]
    assert {j["state"] for j in got} == {wq.DONE}
    beat = hb.read()
    assert beat["state"] == hb.FINISHED and beat["rc"] == 0 and beat[hb.CYCLE]
    assert _holder() == {}, "the sweep's store lease outlived its last step"


def test_a_failed_step_still_queues_the_next_and_the_sweep_ends_nonzero(ran, monkeypatch):
    def body(name, a, sweep, failed):
        ran.append(name)
        if name == "inspect":
            failed.append("inspect")
            return 1
        if name == "disk":
            raise RuntimeError("the disk sweep crashed")
        return 0
    monkeypatch.setattr(steps, "_body", body)
    steps.queue_cycle(_ns())
    _work()
    assert ran == [*steps.NAMES, "settled"]
    states = {j["argv"][j["argv"].index("--step") + 1]: j["state"] for j in wq.jobs() if "--step" in j["argv"]}
    assert states["inspect"] == states["disk"] == wq.FAILED and states["screen"] == wq.DONE
    beat = hb.read()
    assert beat["rc"] == 1 and beat[steps.FAILED][0] == "inspect" and "disk" in beat[steps.FAILED][1]


def test_between_steps_the_sweep_reads_running_while_its_next_step_waits(ran):
    steps.queue_cycle(_ns())
    first = wq.pending()[0]
    _one(first)
    nxt = wq.pending()[0]
    assert nxt["argv"][nxt["argv"].index("--step") + 1] == "repair"
    beat = hb.read()
    assert beat[hb.NEXT_JOB] == nxt["id"]
    assert hb.status(beat, alive=lambda pid: False) == "running"
    assert f"waits in the queue as job {nxt['id']}" in hb.summary(alive=lambda pid: False)["line"]
    wq.cancel(nxt["id"])
    assert hb.status(hb.read(), alive=lambda pid: False) == "stalled"


def test_a_measure_paused_on_request_queues_itself_and_the_next_resumes_the_paused_run(monkeypatch):
    calls = []

    def measure(a, row, sweep):
        calls.append(row["name"])
        if len(calls) > 1:
            return 0
        conn = ms.connect()
        try:
            paused.save(conn, lane="code", inc_spec="inc", spec="org/new", proposal="org/new", out="runs/x",
                        ident={}, plan={}, done=3, total=10, looks=[])
        finally:
            conn.close()
        sweep.halted = "paused on request"
        return watch.PAUSED

    monkeypatch.setattr(measure_cmd, "take_incumbents", lambda want: None)
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", measure)
    monkeypatch.setattr(measure_cmd, "headroom_gb", lambda: 100.0)
    monkeypatch.setattr(loop_cmd, "measure_queue", lambda store, want, top, sweep: measure_cmd.resume_first(
        store, [{"name": "org/other", "lane": "code"}] if not calls else [], want))
    monkeypatch.setattr(loop_cmd, "_gated", lambda row, want: "")
    monkeypatch.setattr(loop_cmd.repo_gate, "args_for", lambda a, row: a)
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **kw: None)
    monkeypatch.setattr(steps, "_settle", lambda sweep: None)
    unloads = []
    monkeypatch.setattr(steps, "_unload", unloads.append)
    steps.queue("measure", "1700000000", _ns())
    first = wq.pending()[0]
    _one(first)
    again = wq.pending()
    assert [j["argv"][j["argv"].index("--step") + 1] for j in again] == ["measure"], "the paused measure was not requeued"
    assert again[0]["id"] != first["id"] and hb.read()["state"] == hb.RUNNING
    assert len(unloads) == 1, "a measure waiting in the queue kept its model loaded"
    _one(again[0])
    assert calls == ["org/other", "org/new"]
    assert wq.pending() == [] and hb.read()["state"] == hb.FINISHED


def test_a_second_sweep_is_not_queued_while_one_has_a_step_waiting(ran, capsys):
    assert steps.queue_cycle(_ns()) == 0
    assert steps.queue_cycle(_ns()) == 1
    assert "not queuing a second" in capsys.readouterr().err
    assert len(wq.pending()) == 1


def test_a_step_stops_its_sweep_while_a_loop_process_holds_the_store_lease(ran):
    conn = ms.connect()
    try:
        assert lease.take(conn, loop_cmd.LEASE, lease.owner(conn), loop_cmd.LEASE_S) == {}
    finally:
        conn.close()
    steps.queue_cycle(_ns())
    first = wq.pending()[0]
    assert _one(first)["rc"] == 1
    assert ran == [] and wq.pending() == []


def test_a_loop_process_refuses_while_a_queued_sweep_holds_the_lease(ran, capsys):
    steps.queue_cycle(_ns())
    first = wq.pending()[0]
    _one(first)
    assert _holder().get("cycle")
    assert loop_cmd._run_loop(_ns()) == 1
    assert "another discover loop holds the store lease" in capsys.readouterr().err


def test_a_step_whose_weights_volume_went_away_pauses_the_sweep(ran, monkeypatch):
    def gone(tier, **kw):
        raise loop_cmd.WeightsGone(tier, "the weights volume /Volumes/WEIGHTS is not mounted")
    monkeypatch.setattr(loop_cmd, "_beat", gone)
    steps.queue_cycle(_ns())
    first = wq.pending()[0]
    assert _one(first)["rc"] == watch.PAUSED
    assert wq.pending() == [] and _holder() == {}
    beat = hb.read()
    assert beat["state"] == hb.FINISHED and beat[hb.PAUSED]["tier"] == "sweep"


def test_a_step_carries_the_loop_options_and_reads_as_a_discover_loop():
    words = steps.argv("fetch", "1700000000", _ns(lane="code", top=3, budget_gib=40.0))
    assert words[words.index("--lane") + 1] == "code" and words[words.index("--top") + 1] == "3"
    assert words[words.index("--budget-gib") + 1] == "40.0" and "--repeat" not in words
    assert sweep_guard.LOOP.search(" ".join(words))


def test_jobs_without_run_queues_nothing(capsys):
    assert cli.main(["discover", "--loop", "--jobs"]) == 2
    assert wq.pending() == []


def test_one_sweep_cannot_release_another_sweeps_lease(ran):
    assert steps._lease("1700000000") == {}
    steps._release("1700000001")
    assert _holder().get("cycle") == "1700000000"
    steps._release("1700000000")
    assert _holder() == {}
