"""paused_runs moves only through paused.MOVES by compare-and-swap, is scoped to this machine, and a run dir has one name. #1730."""
import itertools
import json
import threading
import time

import pytest

from evals import watch
from harness import memory_store as ms
from harness import paused, run_state, watchdog

INC, CH = "llamacpp:Inc", "org/challenger"


@pytest.fixture
def db():
    ms.connect().close()
    return ms.connect


def _save(conn, **kw):
    args = dict(lane="code", inc_spec=INC, spec=CH, proposal=CH, out="/runs/x", ident={}, plan={},
                done=4, total=40, looks=[])
    return paused.save(conn, **{**args, **kw})


def _state(conn, pid):
    return conn.execute("SELECT state FROM paused_runs WHERE id = ?", (pid,)).fetchone()[0]


def test_every_declared_state_is_reached_and_nothing_leaves_a_settled_one():
    assert {s for move in paused.MOVES for s in move} - {None} == set(paused.STATES)
    assert not [m for m in paused.MOVES if m[0] in (paused.STALE, paused.DONE, paused.DEFECT)]


@pytest.mark.parametrize("settled", [paused.STALE, paused.DONE, paused.DEFECT])
def test_a_settled_pause_is_never_revived_by_a_save(db, settled):
    conn = db()
    try:
        pid = _save(conn)
        assert paused.settle(conn, pid, settled, "test")
        with pytest.raises(paused.IllegalMove, match=settled):
            _save(conn, pause_id=pid, done=9)
        row = conn.execute("SELECT state, done FROM paused_runs WHERE id = ?", (pid,)).fetchone()
        assert tuple(row) == (settled, 4)
        assert paused.find(conn, "code", CH) is None
    finally:
        conn.close()


def test_a_save_on_a_live_pause_adds_its_sweeps_and_keeps_it_paused(db):
    conn = db()
    try:
        pid = _save(conn)
        assert _save(conn, pause_id=pid, done=9, spans=2) == pid
        row = conn.execute("SELECT state, done, sweeps FROM paused_runs WHERE id = ?", (pid,)).fetchone()
        assert tuple(row) == (paused.PAUSED, 9, 3)
    finally:
        conn.close()


@pytest.mark.parametrize("to", [paused.PAUSED, "resumed", ""])
def test_a_settle_to_an_undeclared_end_is_refused_and_writes_nothing(db, to):
    conn = db()
    try:
        pid = _save(conn)
        with pytest.raises(paused.IllegalMove):
            paused.settle(conn, pid, to, "test")
        assert _state(conn, pid) == paused.PAUSED
    finally:
        conn.close()


def test_two_racing_settles_one_wins_and_the_loser_writes_nothing(db):
    conn = db()
    try:
        pid = _save(conn)
    finally:
        conn.close()
    gate, got = threading.Barrier(2), {}

    def settle(to):
        c = db()
        try:
            gate.wait()
            got[to] = paused.settle(c, pid, to, f"by {to}")
        finally:
            c.close()

    threads = [threading.Thread(target=settle, args=(to,)) for to in (paused.DONE, paused.STALE)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got.values()) == [False, True]
    (won,) = [to for to, ok in got.items() if ok]
    conn = db()
    try:
        row = conn.execute("SELECT state, why FROM paused_runs WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    assert tuple(row) == (won, f"by {won}")


def test_a_second_live_pause_of_one_pairing_on_this_machine_is_refused(db):
    conn = db()
    try:
        first = _save(conn)
        with pytest.raises(paused.IllegalMove, match="already has a live pause"):
            _save(conn, out="/runs/y")
        assert [r["id"] for r in paused.waiting(conn)] == [first]
        assert paused.settle(conn, first, paused.STALE, "test")
        assert _save(conn, out="/runs/y") != first
    finally:
        conn.close()


def _foreign(conn) -> int:
    now = time.time()
    conn.execute("INSERT INTO machines (fingerprint, hw_model, os, arch, first_seen, last_seen) "
                 "VALUES ('Other/Linux/x86_64/abc', 'Other', 'Linux', 'x86_64', ?, ?)", (now, now))
    conn.commit()
    return conn.execute("SELECT id FROM machines WHERE fingerprint = 'Other/Linux/x86_64/abc'").fetchone()[0]


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/paused.py:find")
def test_another_machines_pause_is_neither_found_nor_waiting_here(db):
    conn = db()
    try:
        there = _foreign(conn)
        assert ms.remember_machine(conn) != there
        theirs = _save(conn, machine_id=there)
        assert paused.find(conn, "code", CH) is None
        assert paused.waiting(conn) == []
        mine = _save(conn, out="/runs/mine")
        assert paused.find(conn, "code", CH)["id"] == mine and mine > theirs
        assert [r["id"] for r in paused.waiting(conn)] == [mine]
    finally:
        conn.close()


def _dir(root, name, candidates, rows=True):
    out = root / name
    out.mkdir(parents=True)
    ck = watch.Checkpoint(out, {"modality": "code", "candidates": candidates, "repeat": 1, "split": "holdout"})
    for i in range(4 if rows else 0):
        ck.add({"case_id": f"c{i}", "candidate": candidates[i % 2], "passed": True, "wall_s": 1.0}, 1.0)
    (out / watch.PROGRESS).write_text(json.dumps({"state": "running", "total": 40}), encoding="utf-8")
    return out


_COMBOS = list(itertools.product([True, False], [True, False], run_state.STATES, [True, False], [True, False]))


@pytest.mark.parametrize("rows,recorded,name,overrun,ours", _COMBOS)
def test_each_run_dir_combination_maps_to_one_named_state(db, tmp_path, monkeypatch, rows, recorded, name, overrun, ours):
    out = _dir(tmp_path / "runs", "20261111-000000-adopt-code", [INC, CH] if ours else [INC, "org/other"], rows)
    monkeypatch.setattr(run_state, "of", lambda o, **k: run_state.State(name, "", {"total": 40}, ""))
    monkeypatch.setattr(watchdog, "overrun_stopped", lambda conn, o: overrun)
    conn = db()
    try:
        if recorded:
            _save(conn, out=str(out))
            paused.settle(conn, paused.find(conn, "code", CH)["id"], paused.STALE, "test")
        got = paused.dir_state(conn, out, "code", INC, CH)
        found = paused.abandoned(conn, tmp_path / "runs", "code", INC, CH)
    finally:
        conn.close()
    assert got in paused.DIR_STATES
    want = (paused.EMPTY if not rows else paused.RECORDED if recorded
            else name if name not in run_state.RESUMABLE else paused.OVERRUN if overrun
            else paused.ABANDONED if ours else paused.OTHER)
    assert got == want
    assert (found is not None) == (got == paused.ABANDONED)
    if found:
        assert found["out"] == str(out) and found["id"] is None and found["done"] == 4
