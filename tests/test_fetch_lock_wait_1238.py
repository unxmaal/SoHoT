"""#1238: the fetch step's router restart waits for the machine lock as the loop, and declares its own bound."""
import contextlib
import json

import pytest

from harness import exclusive, gguf
from harness import heartbeat as hb
from harness import sweep_check as sc
from tests.test_sweep_check_1062 import START, unit

REFRESH = gguf.refresh_router
WAITING = "waiting for eval for 1s (pid 7) to finish"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)


def _holder(**record):
    exclusive.holder_path().write_text(json.dumps({"kind": "eval", "pid": 7, "since": START, **record}),
                                       encoding="utf-8")


def _waits_then_holds(monkeypatch, clock, seen):
    """exclusive.held that waits once behind the holder, snapshotting the loop's heartbeat, then holds."""
    @contextlib.contextmanager
    def held(kind, announce=None, poll=None, deadline_s=None):
        seen.append({"kind": kind, "deadline_s": deadline_s})
        clock["t"] += 600
        if announce:
            announce(WAITING)
        seen[-1]["beat"] = hb.read()
        yield True
    monkeypatch.setattr(exclusive, "held", held)


def _restart():
    return REFRESH(run=lambda *a, **k: None, wait=lambda expect: "")


def test_a_loop_waiting_on_the_router_restarts_lock_reads_running_past_an_hour(monkeypatch):
    clock, seen = {"t": START + 5}, []
    monkeypatch.setattr(hb, "clock", lambda: clock["t"])
    hb.start(lane="", total=10)
    hb.beat("fetch", step=8)
    _holder(deadline_s=4 * 3600)
    _waits_then_holds(monkeypatch, clock, seen)
    assert _restart() == ""
    b = seen[0]["beat"]
    assert b["waiting"] == WAITING
    got = sc.verdict(unit("running"), b, START + 5 + 2 * 3600, START, alive=lambda pid: True)
    assert got["verdict"] == sc.RUNNING, got


def test_the_router_restart_declares_how_long_it_holds_the_machine(monkeypatch):
    seen = []
    _waits_then_holds(monkeypatch, {"t": START}, seen)
    _restart()
    assert seen[0]["kind"] == "external" and seen[0]["deadline_s"] == gguf.READY_TIMEOUT_S


def test_a_router_restart_outside_the_loop_writes_no_heartbeat(monkeypatch):
    seen = []
    _waits_then_holds(monkeypatch, {"t": START}, seen)
    _restart()
    assert hb.read() is None
