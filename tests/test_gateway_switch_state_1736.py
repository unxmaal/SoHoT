"""#1736: an in-flight gateway switch is a row with one declared state; a dead one is finished or reverted, never stranded."""
import contextlib
import subprocess
import sys
import threading

import pytest

from harness import gateway, gateway_switch as gs, gateway_switch_state as st
from harness import memory_store as ms
from tests.test_gateway_switch import STEM, Clock, adopt_for, config, gw  # noqa: F401

GONE = {"pid": 999_999_999, "pgid": 999_999_999, "started": "Thu Jan  1 00:00:00 1970"}


class Died(BaseException):
    """The switch process killed mid-move: nothing in it runs after this."""


def _claim(**ident):
    conn = ms.connect()
    try:
        return st.claim(conn, requested_at=5.0, config=str(gateway.served_path()), **(ident or GONE))
    finally:
        conn.close()


def _row(rid):
    conn = ms.connect()
    try:
        return st.get(conn, rid)
    finally:
        conn.close()


def _history():
    conn = ms.connect()
    try:
        return gs.switches(conn), gs.failures(conn)
    finally:
        conn.close()


def _switch(gw, restart, advance=None):
    clock = Clock()
    return gs.switch(base=gw.base, restart=restart, idle_s=1, max_wait_s=5, poll_s=1,
                     clock=clock.now, sleep=clock.sleep, advance=advance)


def _die():
    raise Died()


def _strand(gw, config):
    """Kill a switch after write_served and its restart call, with the gateway still on the old config."""
    gateway.write_served(config)
    before = gateway.served_path(config).read_text(encoding="utf-8")
    gw.models = gateway.load(gateway.served_path(config))["model_list"]
    adopt_for("code", f"llamacpp:{STEM}")
    rid = _claim()
    with pytest.raises(Died):
        _switch(gw, _die, gs._advance(rid))
    return rid, before


def test_a_switch_killed_after_write_served_is_reverted_and_the_next_switch_serves(gw, config):
    rid, before = _strand(gw, config)
    row = _row(rid)
    assert row["state"] == st.RESTARTING and row["live"] == 1
    path = gateway.served_path(config)
    assert path.read_text(encoding="utf-8") != before
    conn = ms.connect()
    try:
        got = gs.reconcile(conn, alive=lambda r: False, serving=lambda want: "serves the old model")
    finally:
        conn.close()
    assert (got["state"], got["reason"], got["live"]) == (st.FAILED, st.DIED, None)
    assert path.read_text(encoding="utf-8") == before
    done, failed = _history()
    assert done == [] and [f["lane"] for f in failed] == ["code"] and "died" in failed[0]["reason"]
    gw.models = None
    assert [r["lane"] for r in _switch(gw, lambda: None)] == ["code"]


def test_a_switch_killed_after_its_restart_took_is_finished_not_reverted(gw, config):
    rid, before = _strand(gw, config)
    gw.models = None
    target = gateway.served_path(config).read_text(encoding="utf-8")
    conn = ms.connect()
    try:
        got = gs.reconcile(conn, alive=lambda r: False, serving=lambda want: gs.not_serving(gw.base, want))
    finally:
        conn.close()
    assert (got["state"], got["reason"]) == (st.SERVING, st.FINISHED)
    assert gateway.served_path(config).read_text(encoding="utf-8") == target != before
    done, _ = _history()
    assert [(r["lane"], r["new_spec"], r["how"]) for r in done] == [("code", f"llamacpp:{STEM}", "reconciled")]


def test_a_switch_whose_process_lives_is_left_alone(gw, config):
    rid, _ = _strand(gw, config)
    conn = ms.connect()
    try:
        got = gs.reconcile(conn, alive=lambda r: True)
    finally:
        conn.close()
    assert got["id"] == rid and got["state"] == st.RESTARTING


def test_a_dead_switch_leaves_no_drain_behind(config):
    rid = _claim()
    gs.start_drain()
    assert gs.draining()
    conn = ms.connect()
    try:
        gs.reconcile(conn, alive=lambda r: False)
    finally:
        conn.close()
    assert not gs.draining()
    assert (_row(rid)["state"], _row(rid)["reason"]) == (st.FAILED, st.DIED)


def test_two_switches_racing_for_the_slot_one_wins():
    gate = threading.Barrier(6)
    won, lost = [], []

    def claim():
        conn = ms.connect()
        try:
            gate.wait()
            won.append(st.claim(conn, requested_at=1.0, **GONE))
        except st.Lost:
            lost.append(1)
        finally:
            conn.close()

    threads = [threading.Thread(target=claim) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 1 and len(lost) == 5


def test_two_writers_racing_the_same_move_one_wins():
    rid = _claim()
    conn = ms.connect()
    try:
        assert st.move(conn, rid, st.REQUESTED, st.FAILED, st.DIED)
        assert not st.move(conn, rid, st.REQUESTED, st.WRITING, st.QUIET)
        assert st.get(conn, rid)["state"] == st.FAILED
        assert st.live(conn) is None
    finally:
        conn.close()
    assert _claim()


def test_a_move_the_table_does_not_list_is_refused():
    rid = _claim()
    conn = ms.connect()
    try:
        with pytest.raises(st.IllegalMove):
            st.move(conn, rid, st.REQUESTED, st.RESTARTING, st.WRITTEN)
        with pytest.raises(st.IllegalMove):
            st.move(conn, rid, st.REQUESTED, st.SERVING, st.SERVED)
        assert st.get(conn, rid)["state"] == st.REQUESTED
    finally:
        conn.close()


@pytest.mark.skipif(sys.platform == "win32", reason="process groups and ps are POSIX")
def test_a_dead_pid_reused_by_another_process_is_not_mistaken_for_the_switch():
    other = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        real = {"pid": other.pid, "pgid": other.pid, "started": st.started(other.pid)}
        assert real["started"] and st.alive(real) is True
        # Same pid, its own group leader, started at another time: what a reused pid looks like.
        assert st.alive({**real, "started": GONE["started"]}) is False
        assert st.alive({**real, "pgid": real["pgid"] + 1}) is False
        rid = _claim(**{**real, "started": GONE["started"]})
        conn = ms.connect()
        try:
            got = gs.reconcile(conn)
        finally:
            conn.close()
        assert got["id"] == rid and got["state"] == st.FAILED
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_this_process_is_alive_by_its_own_identity():
    assert st.alive(st.me()) is (None if sys.platform == "win32" else True)


def test_spawn_settles_a_dead_switch_and_starts_one_but_not_beside_a_live_one(monkeypatch):
    spawned = []
    monkeypatch.setattr(gs.sys, "platform", "darwin")
    rid = _claim()
    gs.spawn(requested_at=7.0, popen=lambda argv, **kw: spawned.append(argv), alive=lambda r: True)
    assert spawned == [] and _row(rid)["state"] == st.REQUESTED
    gs.spawn(requested_at=7.0, popen=lambda argv, **kw: spawned.append(argv), alive=lambda r: False)
    assert len(spawned) == 1 and _row(rid)["state"] == st.FAILED


@contextlib.contextmanager
def _held(kind, announce=None, deadline_s=None):
    yield


def test_run_takes_the_slot_switches_and_leaves_it_settled(gw, config):
    gateway.write_served(config)
    adopt_for("code", f"llamacpp:{STEM}")
    clock = Clock()

    def switch(**kw):
        return gs.switch(restart=lambda: None, poll_s=1, clock=clock.now, sleep=clock.sleep,
                         **{**kw, "base": gw.base, "idle_s": 1, "max_wait_s": 5})

    assert gs.run(5.0, 1, 5, print, held=_held, ident=st.me(), switch_fn=switch) == st.SERVING
    assert not gs.pending()
    conn = ms.connect()
    try:
        assert st.live(conn) is None
        rows = conn.execute("SELECT state, reason FROM gateway_switch_runs ORDER BY id").fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in rows] == [(st.SERVING, st.SERVED)]
    assert gs.run(5.0, 1, 5, print, held=_held, ident=st.me(), switch_fn=switch) == st.SERVING
    conn = ms.connect()
    try:
        assert conn.execute("SELECT reason FROM gateway_switch_runs ORDER BY id DESC").fetchone()[0] == st.UNCHANGED
    finally:
        conn.close()


def test_run_loses_to_a_live_switch_and_writes_nothing(gw, config):
    rid = _claim()
    assert gs.run(5.0, 1, 5, print, held=_held, alive=lambda r: True, ident=st.me(),
                  switch_fn=lambda **kw: pytest.fail("a losing run must not switch")) == ""
    assert _row(rid)["state"] == st.REQUESTED


def test_a_switch_that_raises_is_settled_and_its_config_put_back(gw, config):
    gateway.write_served(config)
    before = gateway.served_path(config).read_text(encoding="utf-8")
    gw.models = gateway.load(gateway.served_path(config))["model_list"]
    adopt_for("code", f"llamacpp:{STEM}")

    def switch(**kw):
        clock = Clock()
        return gs.switch(restart=lambda: (_ for _ in ()).throw(KeyboardInterrupt()), poll_s=1,
                         clock=clock.now, sleep=clock.sleep, **{**kw, "idle_s": 1, "max_wait_s": 5})

    with pytest.raises(KeyboardInterrupt):
        gs.run(5.0, 1, 5, print, held=_held, ident=st.me(), switch_fn=switch, base=gw.base)
    conn = ms.connect()
    try:
        row = conn.execute("SELECT * FROM gateway_switch_runs").fetchone()
    finally:
        conn.close()
    assert (row["state"], row["reason"], row["live"]) == (st.FAILED, st.RAISED, None)
    assert gateway.served_path(config).read_text(encoding="utf-8") == before


def test_the_view_names_an_unserved_adoption_and_an_orphaned_switch(gw, config):
    gateway.write_served(config)
    conn = ms.connect()
    try:
        assert gs.view(conn)["state"] == st.SERVING
        adopt_for("code", f"llamacpp:{STEM}")
        got = gs.view(conn)
        assert got["state"] == st.STALE and "code" in got["why"]
        rid = _claim()
        assert gs.view(conn, alive=lambda r: True)["state"] == st.REQUESTED
        got = gs.view(conn, alive=lambda r: False)
        assert got["state"] == st.ORPHANED and got["switch"] == rid
    finally:
        conn.close()


def test_the_migration_check_refuses_a_settled_switch_still_holding_the_slot():
    from harness import migration_check as mc
    rid = _claim()
    conn = ms.connect()
    try:
        assert {c.name: c.ok for c in mc.invariants(conn)}["switch_runs_sane"]
        conn.execute("UPDATE gateway_switch_runs SET state = 'serving' WHERE id = ? AND state = 'requested'", (rid,))
        got = {c.name: c for c in mc.invariants(conn)}["switch_runs_sane"]
    finally:
        conn.close()
    assert not got.ok and f"gateway switch {rid}" in got.detail


def test_no_served_config_is_its_own_state(config):
    conn = ms.connect()
    try:
        assert gs.view(conn)["state"] == st.UNWRITTEN
    finally:
        conn.close()
