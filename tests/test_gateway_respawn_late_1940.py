"""#1940: a respawned gateway switch settled unclaimed that claims later is refused and recorded, never switched."""
import sys

import pytest

from harness import gateway_respawn as gr, gateway_switch as gs, gateway_switch_state as st
from harness import memory_store as ms
from harness import paths
from tests.test_gateway_respawn_1904 import _rows, old, posix
from tests.test_gateway_switch import config, gw  # noqa: F401
from tests.test_gateway_switch_repair_1899 import REQUESTED_AT, _claim, _crash, _killed, alerts, started  # noqa: F401

#: The respawned switch: waits for the go file, then claims and runs as gateway_switch.run would, its switch a sentinel.
LATE_SWITCH = r"""
import contextlib, pathlib, sys, time
from harness import gateway_switch as gs
go, ran, out = (pathlib.Path(a) for a in sys.argv[1:4])
while not go.exists():
    time.sleep(0.02)
got = gs.run(float(sys.argv[4]), 1, 5, print, held=lambda *a, **k: contextlib.nullcontext(),
             switch_fn=lambda **kw: ran.write_text("switched", encoding="utf-8"))
out.write_text(got, encoding="utf-8")
"""


@pytest.fixture
def late(monkeypatch, tmp_path):
    """Real respawns whose detached switch claims only once the test says go; their processes and files."""
    procs = []
    real = gs.spawn
    files = {k: tmp_path / k for k in ("go", "ran", "out")}
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    monkeypatch.setattr(gs, "can_restart", lambda: True)
    monkeypatch.setattr(gs, "waiter", lambda requested_at: (
        [sys.executable, "-c", LATE_SWITCH, *map(str, files.values()), repr(float(requested_at))], None))

    def spawn(**kw):
        proc = real(**kw)
        procs.append(proc)
        return proc
    monkeypatch.setattr(gs, "spawn", spawn)
    yield procs, files
    for proc in procs:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()


@posix
def test_a_respawn_that_claims_after_its_unclaimed_settle_is_refused_with_one_outcome_and_one_alert(
        gw, config, late, alerts):
    procs, files = late
    _crash(gw, config)
    assert gs.repair(serving=old)["respawned"] is True
    rec = gr.read()
    got = gs.repair(serving=old, now=rec["spawned_at"] + gr.CLAIM_S)
    assert (got["state"], got["reason"], got["respawned"]) == (st.FAILED, st.UNCLAIMED, False)
    assert procs[0].poll() is None and len(alerts) == 1 and "a claim it makes later is refused" in alerts[0]
    files["go"].touch()
    assert procs[0].wait(timeout=60) == 0
    assert not files["ran"].exists() and files["out"].read_text(encoding="utf-8") == st.FAILED
    settled, refused = _rows()[-2:]
    assert (settled["reason"], refused["state"], refused["reason"], refused["live"], refused["pid"]) == (
        st.UNCLAIMED, st.FAILED, st.LATE, None, rec["pid"])
    assert f"switch {settled['id']} already settled this respawn unclaimed" in refused["detail"]
    conn = ms.connect()
    try:
        assert st.deaths(conn, REQUESTED_AT) == 2 and st.live(conn) is None
    finally:
        conn.close()
    assert gs.repair(serving=old) is None and len(alerts) == 1 and gs.pending()


@posix
def test_a_late_claim_does_not_read_as_the_next_respawn_claiming(gw, config, late, alerts):
    procs, files = late
    _crash(gw, config)
    gs.repair(serving=old)
    rec = gr.read()
    gs.repair(serving=old, now=rec["spawned_at"] + gr.CLAIM_S)
    gs.respawn(REQUESTED_AT)
    second = gr.read()
    assert second["pid"] == procs[1].pid and second["after"] == _rows()[-1]["id"]
    procs[1].kill()
    procs[1].wait()
    files["go"].touch()
    assert procs[0].wait(timeout=60) == 0 and _rows()[-1]["reason"] == st.LATE
    got = gs.repair(serving=old, now=second["spawned_at"] + 1)
    assert (got["reason"], _rows()[-1]["pid"]) == (st.DIED, second["pid"]) and not files["ran"].exists()


@posix
@pytest.mark.gauntlet("two-durable-writes-with-no-repair-for-the-gap", site="harness/gateway_switch.py:run")
def test_a_late_claim_cut_before_its_refusal_is_settled_late_not_counted(gw, config, started, alerts, monkeypatch):
    _crash(gw, config)
    ident = _killed()
    conn = ms.connect()
    try:
        gs.reconcile(conn, serving=old)
        rid = _claim(**ident)
        st.move(conn, rid, st.REQUESTED, st.FAILED, st.UNCLAIMED)
    finally:
        conn.close()

    def cut(*a, **k):
        raise KeyboardInterrupt
    real = st.move
    monkeypatch.setattr(st, "move", cut)
    with pytest.raises(KeyboardInterrupt):
        gs.run(REQUESTED_AT, 1, 5, print, held=lambda *a, **k: pytest.fail("a late claim must not take the lock"),
               ident=ident, switch_fn=lambda **kw: pytest.fail("a late claim must not switch"))
    monkeypatch.setattr(st, "move", real)
    assert (_rows()[-1]["state"], _rows()[-1]["pid"]) == (st.REQUESTED, ident["pid"])
    got = gs.repair(serving=old)
    row = _rows()[-1]
    assert (row["state"], row["reason"], row["live"]) == (st.FAILED, st.LATE, None)
    assert (got["reason"], got["respawned"], got["alerted"]) == (st.LATE, False, "")
    assert started == [] and alerts == [] and gs.repair(serving=old) is None


def test_a_claim_by_any_other_process_is_not_late():
    conn = ms.connect()
    try:
        first = st.claim(conn, requested_at=REQUESTED_AT, config="c", pid=7, started="100.0")
        st.move(conn, first, st.REQUESTED, st.FAILED, st.UNCLAIMED)
        other = st.claim(conn, requested_at=REQUESTED_AT, config="c", pid=7, started="200.0")
        assert gr.late(conn, other) is None and gr.newest(conn) == other
        st.move(conn, other, st.REQUESTED, st.FAILED, st.DIED)
        unknown = st.claim(conn, requested_at=REQUESTED_AT, config="c", pid=8, started="")
        st.move(conn, unknown, st.REQUESTED, st.FAILED, st.UNCLAIMED)
        again = st.claim(conn, requested_at=REQUESTED_AT, config="c", pid=8, started="")
        assert gr.late(conn, again) is None
        st.move(conn, again, st.REQUESTED, st.FAILED, st.DIED)
        reused = st.claim(conn, requested_at=REQUESTED_AT, config="c", pid=9, started="100.0")
        assert gr.late(conn, reused) is None
        st.move(conn, reused, st.REQUESTED, st.FAILED, st.DIED)
        same = st.claim(conn, requested_at=REQUESTED_AT, config="c", pid=7, started="100.0")
        assert gr.late(conn, same) == first and gr.newest(conn) == reused
    finally:
        conn.close()
