"""Another machine's overrun stop of a same-named run dir does not end this machine's run as a defect (#1930)."""
import pytest

from harness import memory_store as ms
from harness import paused, run_state, watchdog
from tests.test_paused_moves_1730 import CH, INC, _dir, _foreign, db  # noqa: F401


def _stop(conn, mid, out, criterion="overrun") -> None:
    conn.execute("INSERT INTO watchdog_actions (at, machine_id, criterion, subject, action, escalated, dry_run, "
                 "outcome, result, run_dir) VALUES (1, ?, ?, 'eval pgid 7', ?, 1, 0, 'group 7: term', ?, ?)",
                 (mid, criterion, watchdog.STOP, watchdog.ACTED, watchdog.canon(out)))
    conn.commit()


def test_another_machines_overrun_stop_of_the_same_run_dir_is_not_this_machines(db, tmp_path):
    out = tmp_path / "runs" / "20261113-000000-adopt-code"
    conn = db()
    try:
        there, mine = _foreign(conn), ms.remember_machine(conn)
        assert there != mine
        _stop(conn, there, out)
        assert not watchdog.overrun_stopped(conn, out)
        _stop(conn, mine, out)
        assert watchdog.overrun_stopped(conn, out)
    finally:
        conn.close()


@pytest.mark.parametrize("ours,want", [(False, paused.ABANDONED), (True, paused.OVERRUN)])
def test_a_run_dir_another_machine_stopped_as_an_overrun_stays_resumable_here(db, tmp_path, monkeypatch, ours, want):
    out = _dir(tmp_path / "runs", "20261113-000000-adopt-code", [INC, CH])
    monkeypatch.setattr(run_state, "of", lambda o, **k: run_state.State(run_state.SIGNALLED, "", {"total": 40}, ""))
    conn = db()
    try:
        there, mine = _foreign(conn), ms.remember_machine(conn)
        _stop(conn, mine if ours else there, out)
        assert paused.dir_state(conn, out, "code", INC, CH) == want
        assert (paused.abandoned(conn, tmp_path / "runs", "code", INC, CH) is not None) == (want == paused.ABANDONED)
    finally:
        conn.close()
