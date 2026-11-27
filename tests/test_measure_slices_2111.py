"""A queue job's measure step is one look of one comparison: a deploy lands between two, the gate holds the next, and the next resumes the paused run. #2111."""
import argparse
import threading
import types

import pytest

from evals import watch
from harness import ceiling, deploy, hold, paths, paused, pressure
from harness import heartbeat as hb
from harness import memory_store as ms
from harness import workqueue as wq
from harness.commands import loop as loop_cmd
from harness.commands import loop_steps as steps
from harness.commands import measure as measure_cmd
from tests import inproc
from tests.test_repo_looks_1353 import Slices
from tests.test_resume_813 import CH, _pauses, _rows, world  # noqa: F401
from tests.test_resume_813 import _ns as _adopt_ns

CYCLE = "1700000000"
DEPLOY = ["true"]


def _ns(**kw):
    base = {"lane": "", "top": None, "repeat": None, "ceiling_h": 11.0,
            "effect": None, "power_budget_min": 30.0, "run": True, "loop": True, "jobs": True}
    return argparse.Namespace(**{**base, **kw})


def _popen(order):
    def popen(argv, **kw):
        if list(argv) == DEPLOY:
            order.append("deploy")
            return types.SimpleNamespace(returncode=0)
        return inproc.popen(argv, **kw)
    return popen


def _work(order=None):
    t = threading.Thread(target=wq.run_pending, kwargs={"popen": _popen(order if order is not None else []),
                                                        "watch": 0.02}, daemon=True)
    t.start()
    t.join(60)
    assert not t.is_alive(), "the worker never ran out of jobs"


def _steps_waiting() -> list[str]:
    return [j["argv"][j["argv"].index("--step") + 1] for j in wq.pending() if not j["not_before"]]


def _pause(name: str, done: int) -> None:
    conn = ms.connect()
    try:
        paused.save(conn, lane="code", inc_spec="inc", spec=name, proposal=name, out="runs/x",
                    ident={}, plan={}, done=done, total=10, looks=[])
    finally:
        conn.close()


def _held(name: str) -> dict | None:
    conn = ms.connect()
    try:
        return paused.find(conn, "code", name)
    finally:
        conn.close()


@pytest.fixture
def step(monkeypatch):
    """The measure step with each comparison's look faked: `look(row, sweep)` is one launch."""
    got = types.SimpleNamespace(rows=["org/a", "org/b"], calls=[], disk=[], unloads=[], look=lambda row, sweep: 0)

    def measure(a, row, sweep):
        got.calls.append(row["name"])
        if sweep.pairs_left:
            sweep.pairs_left -= 1
        return got.look(row, sweep)

    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    monkeypatch.setattr(measure_cmd, "take_incumbents", lambda want: None)
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", measure)
    monkeypatch.setattr(measure_cmd, "headroom_gb", lambda: 100.0)
    monkeypatch.setattr(loop_cmd, "measure_queue", lambda store, want, top, sweep: measure_cmd.resume_first(
        store, [{"name": n, "lane": "code"} for n in got.rows], want))
    monkeypatch.setattr(loop_cmd, "_gated", lambda row, want: "")
    monkeypatch.setattr(loop_cmd.repo_gate, "args_for", lambda a, row: a)
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **kw: None)
    monkeypatch.setattr(loop_cmd, "_after_verdicts", lambda step, **which: got.disk.append(which))
    monkeypatch.setattr(steps, "_settle", lambda sweep: None)
    monkeypatch.setattr(steps, "_unload", got.unloads.append)
    steps.queue("measure", CYCLE, _ns())
    return got


def test_a_measure_job_takes_one_comparison_and_the_next_job_takes_the_rest(step):
    def look(row, sweep):
        step.rows.remove(row["name"])
        return 0
    step.look = look
    first = wq.pending()[0]
    wq.run_one(first, popen=inproc.popen)
    assert step.calls == ["org/a"], "one measure job ran more than one comparison"
    assert _steps_waiting() == ["measure"] and wq.pending()[0]["id"] != first["id"]
    assert step.disk == [] and step.unloads == [], "a slice with work left cleared weights or unloaded its models"
    assert hb.read()["state"] == hb.RUNNING
    _work()
    assert step.calls == ["org/a", "org/b"] and len(step.disk) == 1
    assert _steps_waiting() == [] and hb.read()["state"] == hb.FINISHED


def test_a_comparison_that_launched_nothing_does_not_end_the_job(step):
    def look(row, sweep):
        step.rows.remove(row["name"])
        sweep.pairs_left = 1 if row["name"] == "org/a" else 0
        return 0
    step.look = look
    wq.run_one(wq.pending()[0], popen=inproc.popen)
    assert step.calls == ["org/a", "org/b"] and _steps_waiting() == []


def test_a_look_paused_for_memory_leaves_the_rest_to_the_next_sweep(step):
    def look(row, sweep):
        sweep.squeezed = "memory pressure"
        return watch.PAUSED
    step.look = look
    wq.run_one(wq.pending()[0], popen=inproc.popen)
    assert step.calls == ["org/a"] and _steps_waiting() == [] and hb.read()["state"] == hb.FINISHED


def test_the_ceiling_ends_the_slices_of_a_sweep(step, monkeypatch):
    def look(row, sweep):
        monkeypatch.setattr(ceiling.Sweep, "remaining", lambda self: 0.0)
        return watch.PAUSED
    step.look = look
    wq.run_one(wq.pending()[0], popen=inproc.popen)
    assert _steps_waiting() == ["measure"]
    _work()
    assert step.calls == ["org/a"] and _steps_waiting() == [] and hb.read()["state"] == hb.FINISHED


def test_a_due_deploy_runs_between_two_slices_and_the_next_resumes_the_paused_comparison_with_its_rows(step):
    step.rows = ["org/new"]
    seen = []

    def look(row, sweep):
        held = _held("org/new")
        if held is None:
            _pause("org/new", done=3)
            wq.add(DEPLOY, title="deploy x", kind=deploy.KIND, output="x" * 40, priority=deploy.PRIORITY,
                   cwd=str(paths.home()))
            return watch.PAUSED
        seen.append(held["done"])
        paused.settle_here(held["id"], "done", "finished after 1 pause(s)")
        step.rows.clear()
        return 0
    step.look = look
    wq.run_one(wq.pending()[0], popen=inproc.popen)
    assert step.calls == ["org/new"] and seen == []
    assert [j["kind"] for j in wq.ready()][0] == deploy.KIND, "the deploy does not start before the next slice"
    order = step.calls
    _work(order)
    assert order == ["org/new", "deploy", "org/new"]
    assert seen == [3], "the next slice did not resume the paused comparison with its rows"
    assert hb.read()["state"] == hb.FINISHED and step.unloads == []


def test_the_gate_closing_pauses_a_slice_and_reopening_resumes_it(step, monkeypatch):
    monkeypatch.setattr(wq, "_contended", wq._contended.real)
    monkeypatch.setattr(pressure, "sample", lambda: pressure.Pressure(level=pressure.NORMAL))
    step.rows = ["org/new"]
    seen = []

    def look(row, sweep):
        held = _held("org/new")
        if held is None:
            conn = ms.connect()
            try:
                hold.hold(conn, "the owner is at the machine", scope=hold.GPU)
            finally:
                conn.close()
            _pause("org/new", done=4)
            sweep.halted = "paused on request"
            return watch.PAUSED
        seen.append(held["done"])
        paused.settle_here(held["id"], "done", "finished after 1 pause(s)")
        step.rows.clear()
        return 0
    step.look = look
    wq.run_one(wq.pending()[0], popen=inproc.popen)
    assert _steps_waiting() == ["measure"] and len(step.unloads) == 1, "a slice paused for the gate kept its model loaded"
    _work()
    assert step.calls == ["org/new"] and _steps_waiting() == ["measure"], "a slice started while the gate was closed"
    conn = ms.connect()
    try:
        hold.release(conn, scope=hold.GPU)
    finally:
        conn.close()
    _work()
    assert step.calls == ["org/new", "org/new"] and seen == [4]
    assert _steps_waiting() == [] and hb.read()["state"] == hb.FINISHED


def _look(sweep):
    return measure_cmd._measure(_adopt_ns(), {"name": CH, "lane": "code"}, [], sweep)


def test_a_sliced_measure_job_keeps_looking_at_its_comparison_and_the_next_job_resumes_the_run(monkeypatch, world):
    fake = Slices([_rows(6, gained=1, lost=1), _rows(12, gained=2, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep = ceiling.Sweep(3600.0, pairs_left=2)
    assert _look(sweep) == watch.PAUSED and len(fake.argvs) > 1 and "--resume" in fake.argvs[1]
    assert sweep.pairs_left == 1, "a comparison costs the job one pair, not one per look"
    launched = len(fake.argvs)
    conn = world()
    try:
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert p["state"] == "paused"
    _look(ceiling.Sweep(3600.0, pairs_left=1))
    assert len(fake.argvs) > launched and "--resume" in fake.argvs[launched]


def test_a_measure_with_no_look_limit_goes_on_after_a_look_in_one_launch(monkeypatch, world):
    fake = Slices([_rows(6, gained=1, lost=1), _rows(12, gained=2, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep = ceiling.Sweep(3600.0)
    _look(sweep)
    assert len(fake.argvs) > 1 and "--resume" in fake.argvs[1] and sweep.pairs_left is None
