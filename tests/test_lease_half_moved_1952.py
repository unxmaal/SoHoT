"""A queued job's gpu lease moves to loading and back inside generation.lock; one left loading is mended by the next take. #1952."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from harness import exclusive, item_lease, resources
from harness import memory_store as ms
from harness import workqueue as wq

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv(exclusive.LEASE_ENV, raising=False)
    monkeypatch.delenv(wq.JOB_ENV, raising=False)


def _job() -> tuple[dict, dict]:
    job = wq.add([sys.executable, "-c", "pass"], title="gpu job")
    conn = ms.connect()
    try:
        return job, item_lease.take(conn, resources.GPU, f"job {job['id']}", job_id=int(job["id"]))
    finally:
        conn.close()


def _row(lease_id: int) -> dict:
    conn = ms.connect()
    try:
        return item_lease.row(conn, lease_id)
    finally:
        conn.close()


def _die_loading(job: dict) -> None:
    """A process of the job that takes its lease for an eval and dies before the move back."""
    code = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(REPO)!r})
        from harness import exclusive
        with exclusive.held("eval"):
            os._exit(9)
    """)
    env = {**os.environ, exclusive.HELD_ENV: "", wq.JOB_ENV: str(job["id"])}
    assert subprocess.run([sys.executable, "-c", code], env=env, timeout=60).returncode == 9


@pytest.mark.gauntlet("two-durable-writes-with-no-repair-for-the-gap", site="harness/exclusive.py:_lease")
def test_a_job_process_killed_between_its_two_moves_has_its_lease_mended_by_the_job_s_next_take(monkeypatch):
    job, lease = _job()
    _die_loading(job)
    assert exclusive.state_of(_row(lease["id"])) == exclusive.LOADING, "the killed loader left the lease loading"
    assert exclusive.gpu_holder() == {}, "no process holds generation.lock, so nothing is loading on the GPU"
    monkeypatch.setenv(wq.JOB_ENV, str(job["id"]))
    with exclusive.try_held("image") as got:
        assert got is True, "the job's next take reuses its own lease instead of queueing behind it"
        assert _row(lease["id"])["state"] == "image"
    assert exclusive.state_of(_row(lease["id"])) == exclusive.RESERVED
    item_lease.release(ms.connect(), lease["id"])


def _marks() -> set[int]:
    conn = ms.connect()
    try:
        return exclusive._locked(conn)
    finally:
        conn.close()


def test_a_waiter_outside_the_job_mends_a_lease_its_killed_loader_left_loading():
    job, lease = _job()
    _die_loading(job)
    assert _marks() == {lease["id"]}
    with exclusive.try_held("image") as got:
        assert got is False, "the job still reserves the GPU"
    assert exclusive.state_of(_row(lease["id"])) == exclusive.RESERVED and _marks() == set()
    item_lease.release(ms.connect(), lease["id"])


def test_a_mark_whose_lease_was_released_is_dropped_by_the_next_take():
    job, lease = _job()
    _die_loading(job)
    item_lease.release(ms.connect(), lease["id"])
    assert _marks() == {lease["id"]}
    _, other = _job()
    with exclusive.try_held("image") as got:
        assert got is False
    assert _marks() == set(), "a released lease's mark does not outlive it"
    item_lease.release(ms.connect(), other["id"])


def test_a_lease_an_older_release_left_loading_unmarked_is_not_mended(monkeypatch):
    job, lease = _job()
    conn = ms.connect()
    try:
        assert item_lease.beat(conn, lease["id"], expect="", state="eval"), "an older release's own move, no mark"
    finally:
        conn.close()
    assert exclusive.gpu_holder()["kind"] == "eval", "its loader may not have reached generation.lock yet"
    with exclusive.try_held("image") as got:
        assert got is False
    monkeypatch.setenv(wq.JOB_ENV, str(job["id"]))
    with exclusive.try_held("image") as got:
        assert got is False
    assert _row(lease["id"])["state"] == "eval", "only a lease this release marked inside the lock is mended"
    item_lease.release(ms.connect(), lease["id"])


def test_a_move_back_that_fails_is_said_and_the_next_take_mends_it(monkeypatch, capsys):
    job, lease = _job()
    monkeypatch.setenv(wq.JOB_ENV, str(job["id"]))
    real = exclusive._move

    def down(conn, h, to, writer, **kw):
        if (to, writer) == (exclusive.RESERVED, "own"):
            raise RuntimeError("the store went away")
        return real(conn, h, to, writer, **kw)
    monkeypatch.setattr(exclusive, "_move", down)
    with exclusive.try_held("eval") as got:
        assert got is True
    assert f"gpu lease {lease['id']} was not put back to reserved (the store went away)" in capsys.readouterr().err
    assert exclusive.state_of(_row(lease["id"])) == exclusive.LOADING
    monkeypatch.setattr(exclusive, "_move", real)
    with exclusive.try_held("image") as got:
        assert got is True and _row(lease["id"])["state"] == "image"
    assert exclusive.state_of(_row(lease["id"])) == exclusive.RESERVED
    item_lease.release(ms.connect(), lease["id"])


def test_the_job_s_lease_is_loading_only_while_its_loader_holds_generation_lock(monkeypatch):
    job, lease = _job()
    monkeypatch.setenv(wq.JOB_ENV, str(job["id"]))
    real, seen = exclusive._move, []

    def watch(conn, h, to, writer, **kw):
        if writer == "own":
            seen.append((to, exclusive._taken(exclusive._on_machine(exclusive.lock_path))))
        return real(conn, h, to, writer, **kw)
    monkeypatch.setattr(exclusive, "_move", watch)
    with exclusive.held("eval"):
        assert exclusive.gpu_holder()["kind"] == "eval"
    assert seen == [(exclusive.LOADING, True), (exclusive.RESERVED, True)]
    assert _marks() == set(), "the move back drops the mark with the state"
    item_lease.release(ms.connect(), lease["id"])
