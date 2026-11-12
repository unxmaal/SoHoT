"""The gpu lease row is the one record of who holds the GPU; its moves are tabled, and a lapsed holder that still runs keeps it. #1732."""
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from harness import exclusive, item_lease, paths, resources
from harness import memory_store as ms
from harness import workqueue as wq
from tests.racing import race

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv(exclusive.LEASE_ENV, raising=False)
    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    monkeypatch.delenv(paths.EVAL_ENV, raising=False)


def _take(state="image", pid=None, job_id=None):
    conn = ms.connect()
    try:
        return item_lease.take(conn, resources.GPU, f"{state or 'job'} pid {pid or os.getpid()}", state=state,
                               pid=pid, job_id=job_id)
    finally:
        conn.close()


def _lapse(lease_id, by=1.0):
    conn = ms.connect()
    try:
        conn.execute("UPDATE leases SET expires_at = ? WHERE id = ?", (time.time() - by, int(lease_id)))
        conn.commit()
        return item_lease.row(conn, lease_id)
    finally:
        conn.close()


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _holder(kind, seconds=60):
    code = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(REPO)!r})
        from harness import exclusive
        with exclusive.held({kind!r}):
            print('held', flush=True)
            time.sleep({seconds})
    """)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                         env={**os.environ, exclusive.HELD_ENV: ""})
    assert p.stdout.readline().strip() == "held"
    return p


def test_every_move_is_between_declared_states_and_each_state_has_a_way_out():
    states = {exclusive.FREE, exclusive.RESERVED, exclusive.LOADING, exclusive.LAPSED, exclusive.ABANDONED}
    assert {s for move in exclusive.MOVES for s in move} == states
    for state in states - {exclusive.FREE}:
        assert any(frm == state and to != state for frm, to in exclusive.MOVES), f"{state} has no way out"
    assert (exclusive.LAPSED, exclusive.LOADING) not in exclusive.MOVES, "a lapsed lease is never beaten back to life"


def test_an_illegal_move_is_refused_and_writes_nothing():
    h = _lapse(_take()["id"])
    assert exclusive.state_of(h) == exclusive.LAPSED, "a lapsed lease whose holder runs is lapsed, not free"
    conn = ms.connect()
    try:
        with pytest.raises(exclusive.IllegalMove, match="beat may not move it from lapsed to loading"):
            exclusive._move(conn, h, exclusive.LOADING, "beat", kind="image")
        with pytest.raises(exclusive.IllegalMove, match="reap may not move it from lapsed to free"):
            exclusive._move(conn, h, exclusive.FREE, "reap")
        assert item_lease.row(conn, h["id"]) == h, "a refused move leaves the row as it was"
    finally:
        conn.close()


def test_a_stalled_store_past_the_ttl_does_not_let_a_second_process_take_the_gpu():
    first = _holder("image")
    try:
        conn = ms.connect()
        [h] = item_lease.live(conn, resources.GPU)
        conn.close()
        _lapse(h["id"])
        with exclusive.try_held("eval") as got:
            assert got is False, "the first holder still runs, so its lapsed lease still holds the GPU"
        assert exclusive.gpu_leases() == 1
        assert exclusive.gpu_holder()["lapsed"] is True
        assert wq._free(resources.GPU, {}) is False, "the worker starts no gpu job beside a lapsed holder"
        first.kill()
        first.wait()
        with exclusive.try_held("eval") as got:
            assert got is True, "once the lapsed holder is gone its lease is reaped and the gpu is free"
    finally:
        first.kill()
        first.wait()


def test_a_queued_job_s_lapsed_reservation_still_holds_the_gpu_while_its_process_runs():
    h = _lapse(_take(state="")["id"])
    assert exclusive.state_of(h) == exclusive.LAPSED
    conn = ms.connect()
    try:
        assert exclusive._move(conn, None, exclusive.LOADING, "take", kind="eval") is None
    finally:
        conn.close()
    with exclusive.try_held("eval") as got:
        assert got is False, "no flock is held here, so only the lapsed row stands between the job and a second taker"
    assert exclusive.gpu_leases() == 1


def test_a_lapsed_lease_of_a_dead_holder_is_reaped():
    h = _lapse(_take(pid=_dead_pid())["id"])
    assert exclusive.state_of(h) == exclusive.ABANDONED
    conn = ms.connect()
    try:
        exclusive._reap(conn)
        assert item_lease.row(conn, h["id"])["released_at"] is not None
    finally:
        conn.close()


def test_two_writers_racing_the_same_move_one_loses():
    h = _take(state="")
    assert exclusive.state_of(h) == exclusive.RESERVED
    a, b = ms.connect(), ms.connect()
    try:
        won = exclusive._move(a, h, exclusive.LOADING, "own", kind="eval")
        lost = exclusive._move(b, h, exclusive.LOADING, "own", kind="image")
        assert (won["state"], lost) == ("eval", None), "the second saw reserved, but the row had moved"
        assert item_lease.row(a, h["id"])["state"] == "eval"
    finally:
        a.close()
        b.close()


def test_two_takers_racing_for_a_free_gpu_never_both_win():
    ms.connect().close()
    won = []

    def go(start):
        conn = ms.connect()
        try:
            start()
            got = exclusive._move(conn, None, exclusive.LOADING, "take", kind="image")
            if got is not None:
                won.append(got["id"])
        finally:
            conn.close()
    race([go] * 4)
    assert len(won) == 1


def test_a_holder_whose_beat_cannot_reach_the_store_stops_before_its_ttl_lapses(monkeypatch):
    monkeypatch.setattr(item_lease, "TTL_S", 0.6)
    ticks, tries, lost = [0.0], [], []

    def clock():
        ticks.append(ticks[-1] + 0.1)
        return ticks[-1]
    monkeypatch.setattr(exclusive, "_lost", lambda why: lost.append((ticks[-1], why)))

    def down():
        tries.append(ticks[-1])
        raise OSError("store stalled")
    monkeypatch.setattr(exclusive, "_conn", down)
    stop = exclusive._beating(1, clock=clock)
    try:
        for _ in range(200):
            if lost:
                break
            time.sleep(0.05)
    finally:
        stop.set()
    [(at, why)] = lost
    assert "store stalled" in why
    assert len(tries) == 4, "a failed beat is retried, not taken as lost at once"
    assert at - ticks[1] == pytest.approx(item_lease.TTL_S * 2 / 3), "it stops with a third of its lease still standing"


def test_a_holder_whose_lease_was_released_under_it_stops_at_the_next_beat(monkeypatch):
    h = _take()
    conn = ms.connect()
    item_lease.release(conn, h["id"])
    conn.close()
    monkeypatch.setattr(item_lease, "TTL_S", 0.3)
    lost = []
    monkeypatch.setattr(exclusive, "_lost", lost.append)
    stop = exclusive._beating(h["id"])
    try:
        end = time.monotonic() + 10
        while not lost and time.monotonic() < end:
            time.sleep(0.05)
    finally:
        stop.set()
    assert lost and "released" in lost[0]


def test_a_child_under_a_lapsed_parent_lease_refuses_instead_of_trusting_the_env(monkeypatch):
    h = _take()
    monkeypatch.setenv(exclusive.HELD_ENV, "1")
    monkeypatch.setenv(exclusive.LEASE_ENV, str(h["id"]))
    with exclusive.held("image") as waited:
        assert waited is False, "a child of a holder in force runs under its parent's lease"
    _lapse(h["id"])
    with pytest.raises(exclusive.LeaseLost, match="lapsed"):
        with exclusive.held("image"):
            pass
    with pytest.raises(exclusive.LeaseLost):
        with exclusive.gpu_now("image"):
            pass


def test_held_hands_its_lease_to_children_and_takes_it_back():
    with exclusive.held("image"):
        conn = ms.connect()
        [h] = item_lease.live(conn, resources.GPU)
        conn.close()
        assert os.environ[exclusive.LEASE_ENV] == str(h["id"])
        assert exclusive.holder()["lease"] == h["id"]
    assert exclusive.HELD_ENV not in os.environ and exclusive.LEASE_ENV not in os.environ


def test_the_holder_record_counts_only_when_it_names_the_lease():
    h = _take(state="video")
    exclusive.holder_path().write_text(json.dumps({"kind": "image", "pid": os.getpid(), "since": 1.0}),
                                       encoding="utf-8")
    assert exclusive.gpu_holder()["kind"] == "video", "a record naming no lease does not say who holds the GPU"
    exclusive.holder_path().write_text(json.dumps({"kind": "image", "pid": os.getpid(), "since": 1.0,
                                                   "lease": h["id"]}), encoding="utf-8")
    assert exclusive.gpu_holder()["kind"] == "image"


def test_the_holder_record_of_a_scratch_eval_home_lives_in_the_machine_home(tmp_path, monkeypatch):
    live = paths.home()
    monkeypatch.delenv(paths.ENV_VAR)
    scratch = paths.eval_home(tmp_path / "scratch")
    assert (paths.home(), paths.machine_home()) == (scratch, live)
    assert exclusive.holder_path() == live / "queue" / exclusive.HOLDER
