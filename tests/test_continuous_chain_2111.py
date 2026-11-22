"""A queued sweep whose chain broke is put back in the queue: a dead step, a refused lease, a successor that could not be queued. #2111."""
import argparse
import os
import threading
import time

import pytest

from harness import contention, env, job_claim, job_settle, lease
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


def _one(job) -> dict:
    return wq.run_one(job, popen=inproc.popen)


def _work():
    t = threading.Thread(target=wq.run_pending, kwargs={"popen": inproc.popen, "watch": 0.02}, daemon=True)
    t.start()
    t.join(60)
    assert not t.is_alive(), "the worker never ran out of steps"


def _name(job) -> str:
    return job["argv"][job["argv"].index("--step") + 1]


def _cycle(job) -> str:
    return job["argv"][job["argv"].index("--cycle") + 1]


def _die(job) -> None:
    """The job's worker and process went away mid-run, and the next worker settles it."""
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    job_claim.path(job["id"]).write_text(
        f'{{"pid": {os.getpid()}, "pgid": {os.getpid()}, "started": "1.000000"}}', encoding="utf-8")
    job_settle._recover()
    assert wq.get(job["id"])["state"] == wq.FAILED


def _started_to(name: str) -> dict:
    """A sweep queued by hand and run until step `name` is the one waiting."""
    assert steps.queue_cycle(_ns()) == 0
    while _name(wq.pending()[0]) != name:
        _one(wq.pending()[0])
    return wq.pending()[0]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    monkeypatch.setattr(steps, "_SAID", [""])


@pytest.fixture
def ran(monkeypatch):
    got = []
    monkeypatch.setattr(steps, "_body", lambda name, a, sweep, failed: got.append(name) or 0)
    monkeypatch.setattr(steps, "_settle", lambda sweep: got.append("settled"))
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **kw: hb.beat(tier, step=1))
    return got


def test_a_step_that_died_is_followed_by_the_next_step_of_its_sweep_once(ran, capsys):
    dead = _started_to("repair")
    _die(dead)
    assert wq.pending() == [], "the control: a dead step leaves nothing waiting"
    steps.turn()
    steps.turn()
    nxt, = wq.pending()
    assert (_name(nxt), _cycle(nxt)) == ("runtimes", _cycle(dead)) and wq.due(nxt)
    assert capsys.readouterr().out.count("ended at its repair step") == 1
    _work()
    assert ran == ["sweep", *steps.NAMES[2:], "settled"], "the dead step ran again, or the sweep did not go on"


def test_a_dead_step_carries_the_sweeps_options_to_what_follows(ran):
    steps.queue("retests", "1700000000", _ns(lane="code", top=3))
    _one(wq.pending()[0])
    _die(wq.pending()[0])
    steps.turn()
    words = wq.pending()[0]["argv"]
    assert words[words.index("--lane") + 1] == "code" and words[words.index("--top") + 1] == "3"
    assert words[words.index("--ceiling-h") + 1] == "11.0"


def test_a_last_step_that_died_is_followed_by_the_next_sweep_after_the_idle_window(ran):
    dead = _started_to(steps.NAMES[-1])
    before = time.time()
    _die(dead)
    steps.turn()
    nxt, = wq.pending()
    assert _cycle(nxt) != _cycle(dead) and _name(nxt) == "retests"
    assert not wq.due(nxt, before + contention.IDLE_S - 5) and wq.due(nxt, time.time() + contention.IDLE_S + 1)


def test_a_cancelled_step_is_the_owners_stop_and_nothing_follows_it(ran):
    wq.cancel(_started_to("repair")["id"])
    steps.turn()
    assert wq.pending() == []


def test_a_step_job_left_from_before_the_loop_process_last_swept_starts_nothing(ran):
    _die(_started_to("repair"))
    hb.start(total=loop_cmd.LOOP_TOTAL)
    hb.finish(0)
    steps.turn()
    assert wq.pending() == [], "an old one-sweep job turned continuous discovery on"


def test_nothing_follows_a_sweep_with_a_step_still_waiting(ran):
    waiting = _started_to("repair")
    steps.turn()
    assert [j["id"] for j in wq.pending()] == [waiting["id"]]


def test_a_dead_step_waits_for_the_weights_volume(ran, monkeypatch, capsys):
    _die(_started_to("repair"))
    monkeypatch.setattr(env, "unmounted", lambda roots: "/Volumes/WEIGHTS")
    steps.turn()
    assert wq.pending() == [] and "/Volumes/WEIGHTS" in capsys.readouterr().out
    monkeypatch.setattr(env, "unmounted", lambda roots: "")
    steps.turn()
    assert [_name(j) for j in wq.pending()] == ["runtimes"]


def test_a_step_refused_the_lease_asks_again_after_the_idle_window_and_runs_once_it_is_free(ran):
    conn = ms.connect()
    try:
        who = lease.owner(conn)
        assert lease.take(conn, loop_cmd.LEASE, who, loop_cmd.LEASE_S) == {}
        steps.queue_cycle(_ns())
        first = wq.pending(conn)[0]
        before = time.time()
        assert _one(first)["rc"] == 1
        again, = wq.pending(conn)
        assert (_name(again), _cycle(again)) == (_name(first), _cycle(first)) and again["id"] != first["id"]
        assert not wq.due(again, before + contention.IDLE_S - 5), "a refused step asks again at once"
        assert _one(again)["rc"] == 1 and len(wq.pending(conn)) == 1, "a step refused twice left other than one waiting"
        lease.release(conn, loop_cmd.LEASE, who)
    finally:
        conn.close()
    assert ran == []
    _one(wq.pending()[0])
    assert ran == [steps.NAMES[0]] and _name(wq.pending()[0]) == steps.NAMES[1]


def test_a_successor_that_could_not_be_queued_is_queued_at_the_workers_turn(ran, monkeypatch, capsys):
    first = _started_to("repair")
    real = wq.add

    def refuse(*args, **kw):
        raise ValueError("not queued: this release speaks schema 1 but the store is at 2")
    monkeypatch.setattr(wq, "add", refuse)
    assert _one(first)["rc"] == 1 and wq.pending() == []
    steps.turn()
    steps.turn()
    assert wq.pending() == [] and capsys.readouterr().out.count("could not be queued") == 1
    monkeypatch.setattr(wq, "add", real)
    steps.turn()
    assert [(_name(j), _cycle(j)) for j in wq.pending()] == [("runtimes", _cycle(first))]


def test_the_worker_mends_a_broken_sweep_each_turn(ran):
    _die(_started_to("repair"))
    wq.serve(forever=False, gate_fn=lambda: (False, "the gate is closed"))
    assert [_name(j) for j in wq.pending()] == ["runtimes"]


def test_the_loop_process_puts_a_broken_sweep_back_rather_than_sweep_itself(ran, monkeypatch, capsys):
    monkeypatch.setattr(loop_cmd, "_run_loop", lambda a: pytest.fail("the loop process swept over a broken queued sweep"))
    _die(_started_to("repair"))
    beat = hb.read()
    assert loop_cmd._report_loop(_ns(jobs=False)) == 0
    assert [_name(j) for j in wq.pending()] == ["runtimes"] and hb.read() == beat
    assert "ended at its repair step" in capsys.readouterr().out


def test_a_dry_loop_mends_nothing(ran, monkeypatch):
    monkeypatch.setattr(loop_cmd, "_run_loop", lambda a: 0)
    _die(_started_to("repair"))
    assert loop_cmd._report_loop(_ns(jobs=False, run=False)) == 0
    assert wq.pending() == []
