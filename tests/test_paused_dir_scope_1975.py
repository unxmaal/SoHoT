"""Another machine's pause of a same-named run dir does not make this machine's dir recorded (#1975)."""
import pytest

from harness import memory_store as ms
from harness import paused, run_state, watchdog
from tests.test_paused_moves_1730 import CH, INC, _dir, _foreign, _save, db  # noqa: F401


@pytest.mark.parametrize("whose,want", [("there", paused.ABANDONED), ("nobody", paused.ABANDONED),
                                        ("mine", paused.RECORDED)])
def test_only_this_machines_pause_of_a_run_dir_marks_it_recorded(db, tmp_path, monkeypatch, whose, want):
    out = _dir(tmp_path / "runs", "20261113-000000-adopt-code", [INC, CH])
    monkeypatch.setattr(run_state, "of", lambda o, **k: run_state.State(run_state.SIGNALLED, "", {"total": 40}, ""))
    monkeypatch.setattr(watchdog, "overrun_stopped", lambda conn, o: False)
    conn = db()
    try:
        there, mine = _foreign(conn), ms.remember_machine(conn)
        assert there != mine
        pid = _save(conn, out=str(out), machine_id=mine if whose == "mine" else there)
        assert paused.settle(conn, pid, paused.STALE, "test")
        if whose == "nobody":
            conn.execute("UPDATE paused_runs SET machine_id = NULL WHERE id = ?", (pid,))
            conn.commit()
        assert paused.dir_state(conn, out, "code", INC, CH) == want
        found = paused.abandoned(conn, tmp_path / "runs", "code", INC, CH)
        assert (found is not None) == (want == paused.ABANDONED)
    finally:
        conn.close()
