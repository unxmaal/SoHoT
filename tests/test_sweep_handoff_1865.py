"""A step's successor is startable only once the heartbeat names it, and two threads writing the heartbeat both land. #1865."""
import argparse
import os
import threading

from harness import heartbeat as hb
from harness import memory_store as ms
from harness import workqueue as wq
from harness.commands import loop as loop_cmd
from harness.commands import loop_steps as steps


def _ns(**kw):
    base = {"lane": "", "top": None, "budget_gib": None, "repeat": None, "ceiling_h": 11.0,
            "effect": None, "power_budget_min": 30.0, "run": True, "loop": True, "jobs": True}
    return argparse.Namespace(**{**base, **kw})


def _visible(name: str) -> list[str]:
    """The jobs of step `name` a worker's own connection sees pending, as the worker would read them."""
    conn = ms.connect()
    try:
        return [j["id"] for j in wq.pending(conn) if steps._step_of(j["argv"]) == name]
    finally:
        conn.close()


def test_the_next_step_is_not_startable_until_the_heartbeat_hands_off_to_it(monkeypatch):
    seen = []
    real = hb.handoff

    def handoff(job, tier):
        seen.append(_visible("repair"))
        return real(job, tier)
    monkeypatch.setattr(hb, "handoff", handoff)
    monkeypatch.setattr(steps, "_body", lambda name, a, sweep, failed: 0)
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **kw: hb.beat(tier, step=1))
    steps.queue_cycle(_ns())
    first = wq.pending()[0]
    monkeypatch.setenv(wq.JOB_ENV, str(int(first["id"])))
    assert steps.run_step(_ns(step="sweep", cycle=steps._cycle_of(first["argv"]))) == 0
    assert seen == [[]], "a worker could start the repair step before the sweep step's heartbeat named it"
    nxt = _visible("repair")
    assert len(nxt) == 1 and hb.read()[hb.NEXT_JOB] == nxt[0]


def test_two_threads_writing_the_heartbeat_both_land(monkeypatch):
    both = threading.Barrier(2, timeout=10)
    real = os.replace
    errors = []
    met = set()

    def replace(src, dst):
        if threading.get_ident() not in met:  # a Windows retry (#1905) must not wait for a partner again
            met.add(threading.get_ident())
            both.wait()
        return real(src, dst)
    monkeypatch.setattr(hb.os, "replace", replace)

    def write(n):
        try:
            hb._write({"writer": n})
        except Exception as exc:  # noqa: BLE001 - the failure under test
            errors.append(exc)
    threads = [threading.Thread(target=write, args=(n,)) for n in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert not any(t.is_alive() for t in threads)
    assert errors == [], "one thread's heartbeat write lost its temp file to the other's"
    assert hb.read()["writer"] in (1, 2)
