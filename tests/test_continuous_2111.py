"""A closed queued sweep queues the next once, its find half left out inside the schedule's gap; the loop process stays out while one is live. #2111."""
import argparse
import threading
import time

import pytest

from harness import contention, hold
from harness import heartbeat as hb
from harness import memory_store as ms
from harness import workqueue as wq
from harness.commands import loop as loop_cmd
from harness.commands import loop_steps as steps
from tests import inproc


def _ns(**kw):
    base = {"lane": "", "top": None, "repeat": None, "ceiling_h": 11.0,
            "effect": None, "power_budget_min": 30.0, "run": True, "loop": True, "jobs": True}
    return argparse.Namespace(**{**base, **kw})


def _work():
    t = threading.Thread(target=wq.run_pending, kwargs={"popen": inproc.popen, "watch": 0.02}, daemon=True)
    t.start()
    t.join(60)
    assert not t.is_alive(), "the worker never ran out of steps"


def _sql(text: str, *args) -> None:
    conn = ms.connect()
    try:
        conn.execute(text, args)
        conn.commit()
    finally:
        conn.close()


def _name(job) -> str:
    return job["argv"][job["argv"].index("--step") + 1]


def _cycle(job) -> str:
    return job["argv"][job["argv"].index("--cycle") + 1]


def _steps_of(cycle: str) -> list[str]:
    return [_name(j) for j in wq.jobs() if "--step" in j["argv"] and _cycle(j) == cycle]


@pytest.fixture(autouse=True)
def _no_job(monkeypatch):
    monkeypatch.delenv(wq.JOB_ENV, raising=False)


@pytest.fixture
def ran(monkeypatch):
    got = []
    monkeypatch.setattr(steps, "_body", lambda name, a, sweep, failed: got.append(name) or 0)
    monkeypatch.setattr(steps, "_settle", lambda sweep: got.append("settled"))
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **kw: hb.beat(tier, step=1))
    return got


def _closed_once() -> dict:
    """One whole sweep run to its close; the job that waits after it."""
    assert steps.queue_cycle(_ns()) == 0
    _work()
    waiting = wq.pending()
    assert len(waiting) == 1, "a closed sweep left other than one sweep waiting"
    return waiting[0]


def test_a_closed_sweep_queues_the_next_once_due_after_the_idle_window(ran):
    before = time.time()
    nxt = _closed_once()
    first = _steps_of(next(c for c in {_cycle(j) for j in wq.jobs()} if c != _cycle(nxt)))
    assert first == list(steps.NAMES) and ran[-1] == "settled"
    assert nxt["requested_by"] == "discover" and nxt["resource"] == steps.step(_name(nxt)).resource
    assert not wq.due(nxt, before + contention.IDLE_S - 5), "the next sweep is due inside the idle window"
    assert wq.due(nxt, time.time() + contention.IDLE_S + 1)
    assert hb.read()["state"] == hb.FINISHED, "the closed sweep still reads as running"


def test_a_retried_last_step_queues_no_second_sweep(ran):
    nxt = _closed_once()
    last = next(j for j in wq.jobs() if "--step" in j["argv"] and _name(j) == steps.NAMES[-1])
    _sql("UPDATE jobs SET state = ?, finished_at = NULL, rc = NULL WHERE id = ?", wq.PENDING, int(last["id"]))
    _work()
    assert [j["id"] for j in wq.pending()] == [nxt["id"]]
    assert ran.count(steps.NAMES[-1]) == 1


def test_a_closing_sweep_queues_none_beside_another_that_waits(ran):
    steps.queue_cycle(_ns())
    other = steps.queue("retests", "424242", _ns(), not_before=time.time() + 3600)
    _work()
    assert ran[-1] == "settled"
    assert [j["id"] for j in wq.pending()] == [other["id"]]


def test_a_sweep_that_closes_under_a_benchmarks_hold_still_queues_the_next_which_waits_for_the_release(ran):
    steps.queue_cycle(_ns())
    conn = ms.connect()
    try:
        hold.hold(conn, "the owner: a quiet afternoon")
        cycle = _cycle(wq.pending(conn)[0])
        while _cycle(wq.pending(conn)[0]) == cycle:
            wq.run_one(wq.pending(conn)[0], popen=inproc.popen)
        nxt, = wq.pending(conn)
        later = time.time() + contention.IDLE_S + 60
        assert wq.ready(conn, later) == []
        hold.release(conn)
        assert [j["id"] for j in wq.ready(conn, later)] == [nxt["id"]]
    finally:
        conn.close()


def test_the_next_sweep_is_the_spend_half_alone_inside_the_schedules_gap(ran):
    nxt = _closed_once()
    assert steps.SPACED == ("sweep", "repair", "runtimes", "inspect", "queue")
    assert _name(nxt) == "retests", "the feeds were read minutes ago; the next sweep starts with them again"
    del ran[:]
    _sql("UPDATE jobs SET not_before = NULL WHERE id = ?", int(nxt["id"]))
    _work()
    want = [n for n in steps.NAMES if n not in steps.SPACED]
    assert ran == [*want, "settled"] and _steps_of(_cycle(nxt)) == want


def test_the_next_sweep_runs_the_find_half_again_once_the_schedules_gap_is_over(ran):
    assert steps.queue_cycle(_ns()) == 0
    first = wq.pending()[0]
    wq.run_one(first, popen=inproc.popen)
    gap = hb.sweep_every_s(hb.discover_hours())
    _sql("UPDATE jobs SET started_at = started_at - ? WHERE id = ?", gap, int(first["id"]))
    _work()
    nxt = wq.pending()[0]
    assert _name(nxt) == steps.NAMES[0]
    del ran[:]
    _sql("UPDATE jobs SET not_before = NULL WHERE id = ?", int(nxt["id"]))
    _work()
    assert ran == [*steps.NAMES, "settled"]


def test_a_sweep_queued_by_hand_runs_every_step_whenever_the_feeds_were_last_read(ran):
    nxt = _closed_once()
    wq.cancel(nxt["id"])
    del ran[:]
    while str(int(time.time())) in {_cycle(j) for j in wq.jobs()}:  # a sweep is named for its second
        time.sleep(0.05)
    assert steps.queue_cycle(_ns()) == 0
    _work()
    assert ran[:len(steps.NAMES) + 1] == [*steps.NAMES, "settled"]


def test_the_loop_process_starts_nothing_while_a_queued_sweep_has_a_step_waiting(ran, monkeypatch, capsys):
    monkeypatch.setattr(loop_cmd, "_run_loop", lambda a: pytest.fail("the loop process ran beside a queued sweep"))
    steps.queue_cycle(_ns())
    wq.run_one(wq.pending()[0], popen=inproc.popen)
    beat = hb.read()
    assert loop_cmd._report_loop(_ns(jobs=False)) == 0
    assert "runs as queue jobs" in capsys.readouterr().out
    assert hb.read() == beat, "the loop process overwrote the queued sweep's heartbeat"


def test_the_loop_process_stays_out_between_two_queued_sweeps(ran, monkeypatch):
    monkeypatch.setattr(loop_cmd, "_run_loop", lambda a: pytest.fail("the loop process ran before the next queued sweep"))
    _closed_once()
    assert loop_cmd._report_loop(_ns(jobs=False)) == 0


def test_the_loop_process_runs_when_no_queued_sweep_is_live(ran, monkeypatch):
    calls = []
    monkeypatch.setattr(loop_cmd, "_run_loop", lambda a: calls.append(a) or 0)
    nxt = _closed_once()
    wq.cancel(nxt["id"])
    assert loop_cmd._report_loop(_ns(jobs=False)) == 0
    assert len(calls) == 1 and hb.read().get(hb.CYCLE) is None


def test_a_dry_loop_is_not_refused_by_a_queued_sweep(ran, monkeypatch):
    calls = []
    monkeypatch.setattr(loop_cmd, "_run_loop", lambda a: calls.append(a) or 0)
    steps.queue_cycle(_ns())
    assert loop_cmd._report_loop(_ns(jobs=False, run=False)) == 0
    assert len(calls) == 1
