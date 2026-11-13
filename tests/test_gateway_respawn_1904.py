"""#1904: a gateway switch the worker started again that dies before claiming its row is settled and counted, once."""
import json
import sys

import pytest

from harness import gateway, gateway_respawn as gr, gateway_switch as gs, gateway_switch_state as st
from harness import memory_store as ms
from harness import paths
from tests.test_gateway_switch import config, gw  # noqa: F401
from tests.test_gateway_switch_repair_1899 import REQUESTED_AT, _claim, _crash, alerts  # noqa: F401

posix = pytest.mark.skipif(sys.platform == "win32", reason="proc_identity cannot judge a pid on Windows")


def old(want):
    return "serves the old model"


@pytest.fixture
def respawned(monkeypatch):
    """Real respawns from the live home whose detached switch is a sleeper that never claims; their processes."""
    procs = []
    real = gs.spawn
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    monkeypatch.setattr(gs, "can_restart", lambda: True)
    monkeypatch.setattr(gs, "waiter", lambda requested_at: ([sys.executable, "-c", "import time; time.sleep(60)"], None))

    def spawn(**kw):
        proc = real(**kw)
        procs.append(proc)
        return proc
    monkeypatch.setattr(gs, "spawn", spawn)
    yield procs
    for proc in procs:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()


def _rows():
    conn = ms.connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM gateway_switch_runs ORDER BY id")]
    finally:
        conn.close()


def _kill(proc):
    proc.kill()
    proc.wait()


def _cuts():
    conn = ms.connect()
    try:
        return [(r[0], r[1]) for r in conn.execute("SELECT value, dropped FROM limit_cuts WHERE knob = ?",
                                                    ("gateway_respawn_claim",))]
    finally:
        conn.close()


@posix
def test_a_respawn_killed_before_its_claim_is_settled_once_and_alerted_once(gw, config, respawned, alerts):
    _crash(gw, config)
    assert gs.repair(serving=old)["respawned"] is True
    rec = gr.read()
    assert rec["requested_at"] == REQUESTED_AT and rec["pid"] == respawned[0].pid
    _kill(respawned[0])
    before = len(_rows())
    got = gs.repair(serving=old, now=rec["spawned_at"] + gr.CLAIM_S + 1)
    settled = _rows()[before:]
    assert [(r["state"], r["reason"], r["live"], r["requested_at"], r["pid"]) for r in settled] == [
        (st.FAILED, st.DIED, None, REQUESTED_AT, rec["pid"])]
    assert (got["switch"], got["respawned"]) == (settled[0]["id"], False)
    assert len(alerts) == 1 and alerts[0] == got["alerted"] and "died 2 times" in alerts[0]
    assert "while starting" in alerts[0] and gr.read() is None and len(respawned) == 1
    assert gs.repair(serving=old, now=rec["spawned_at"] + 2 * gr.CLAIM_S) is None
    assert len(_rows()) == before + 1 and len(alerts) == 1


@posix
def test_a_live_unclaimed_respawn_is_left_alone_inside_the_deadline_and_settled_past_it(gw, config, respawned, alerts):
    _crash(gw, config)
    gs.repair(serving=old)
    rec, before = gr.read(), len(_rows())
    assert gs.repair(serving=old, now=rec["spawned_at"] + gr.CLAIM_S - 1) is None
    assert gr.read() == rec and len(_rows()) == before and alerts == [] and respawned[0].poll() is None
    got = gs.repair(serving=old, now=rec["spawned_at"] + gr.CLAIM_S)
    assert (got["state"], got["reason"], got["respawned"]) == (st.FAILED, st.UNCLAIMED, False)
    assert "had not claimed it 300 s" in _rows()[-1]["detail"] and len(alerts) == 1
    assert _cuts() == [(gr.CLAIM_S, 1)]


@posix
def test_a_respawn_whose_process_cannot_be_judged_waits_for_the_deadline(gw, config, respawned, alerts):
    _crash(gw, config)
    gs.repair(serving=old)
    rec, before = gr.read(), len(_rows())
    _kill(respawned[0])
    assert gs.repair(serving=old, now=rec["spawned_at"] + 1, same=lambda r: None) is None
    assert len(_rows()) == before and gr.read() == rec
    got = gs.repair(serving=old, now=rec["spawned_at"] + gr.CLAIM_S, same=lambda r: None)
    assert (got["state"], got["reason"]) == (st.FAILED, st.UNCLAIMED) and len(alerts) == 1


@posix
@pytest.mark.gauntlet("two-durable-writes-with-no-repair-for-the-gap", site="harness/gateway_respawn.py:unclaimed")
def test_a_settle_cut_between_its_claim_and_its_move_is_repaired_next_pass(gw, config, respawned, alerts,
                                                                           monkeypatch):
    _crash(gw, config)
    gs.repair(serving=old)
    rec = gr.read()
    _kill(respawned[0])

    def cut(*a, **k):
        raise KeyboardInterrupt
    real = st.move
    monkeypatch.setattr(st, "move", cut)
    with pytest.raises(KeyboardInterrupt):
        gs.repair(serving=old)
    monkeypatch.setattr(st, "move", real)
    assert _rows()[-1]["state"] == st.REQUESTED and gr.read() == rec
    got = gs.repair(serving=old)
    row = _rows()[-1]
    assert (row["state"], row["reason"], row["live"], row["pid"]) == (st.FAILED, st.DIED, None, rec["pid"])
    assert got["respawned"] is False and len(alerts) == 1
    assert gs.repair(serving=old) is None and gr.read() is None and len(alerts) == 1


@posix
@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates",
                      site="harness/gateway_respawn.py:mark")
def test_a_respawn_that_claimed_its_row_is_cleared_not_settled(gw, config, respawned, alerts):
    _crash(gw, config)
    gs.repair(serving=old)
    rec = gr.read()
    conn = ms.connect()
    try:
        rid = st.claim(conn, requested_at=REQUESTED_AT, config=str(gateway.served_path()), pid=rec["pid"],
                       pgid=rec["pgid"], started=rec["started"])
        st.move(conn, rid, st.REQUESTED, st.SERVING, st.UNCHANGED)
    finally:
        conn.close()
    _kill(respawned[0])
    before = len(_rows())
    assert gs.repair(serving=old, now=rec["spawned_at"] + gr.CLAIM_S + 1) is None
    assert gr.read() is None and len(_rows()) == before and alerts == []


@posix
def test_a_respawn_is_marked_before_its_process_starts(gw, config, monkeypatch):
    seen = []
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())

    def spawn(**kw):
        seen.append(gr.read())
        raise OSError("no fork")
    monkeypatch.setattr(gs, "spawn", spawn)
    with pytest.raises(OSError):
        gs.respawn(REQUESTED_AT)
    assert seen[0]["requested_at"] == REQUESTED_AT and seen[0]["pid"] is None and gr.read() is None
    monkeypatch.setattr(gs, "spawn", lambda **kw: None)
    gs.respawn(REQUESTED_AT)
    assert gr.read() is None


def test_no_mark_is_nothing_to_settle(gw, config, alerts):
    assert gs.repair() is None and _rows() == [] and alerts == []


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/gateway_respawn.py:read:except")
def test_an_unreadable_mark_is_removed_and_settles_nothing(gw, config, alerts):
    assert gr.read() is None
    gr.path().write_text("{not json", encoding="utf-8")
    assert gr.read() == {}
    assert gs.repair() is None and not gr.path().exists() and _rows() == []
    gr.path().write_text(json.dumps({"requested_at": 1.0}), encoding="utf-8")
    assert gs.repair() is None and not gr.path().exists()


def test_an_unclaimed_settle_counts_against_the_respawn_bound():
    conn = ms.connect()
    try:
        for reason in (st.DIED, st.UNCLAIMED, st.RAISED):
            rid = st.claim(conn, requested_at=REQUESTED_AT, config="c", pid=1)
            st.move(conn, rid, st.REQUESTED, st.FAILED, reason)
        assert st.deaths(conn, REQUESTED_AT) == 2
    finally:
        conn.close()
