"""A gpu lease names its holder by pid, group and start time, so a reused pid holds nothing; held()'s wait is bounded. #1772, #1763."""
import contextlib
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from harness import exclusive, item_lease, monitor, paths, proc_identity, resources
from harness import memory_store as ms
from harness import workqueue as wq

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv(exclusive.LEASE_ENV, raising=False)
    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    monkeypatch.delenv(paths.EVAL_ENV, raising=False)


def _holder(kind="image", seconds=120):
    code = textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {str(REPO)!r})
        from harness import exclusive
        with exclusive.held({kind!r}):
            print('held', os.getpid(), flush=True)
            time.sleep({seconds})
    """)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                         env={**os.environ, exclusive.HELD_ENV: ""})
    said, _, pid = p.stdout.readline().partition(" ")
    assert said == "held"
    # A Windows venv's python.exe is a launcher: the lease is held by its child.
    p.holder = int(pid)
    return p


def _row_of(pid):
    conn = ms.connect()
    try:
        return next(h for h in item_lease.unreleased(conn, resources.GPU) if h["pid"] == pid)
    finally:
        conn.close()


def _set(lease_id, **fields):
    conn = ms.connect()
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE leases SET {sets} WHERE id = ?", (*fields.values(), int(lease_id)))
        conn.commit()
        return item_lease.row(conn, lease_id)
    finally:
        conn.close()


def _kill(p):
    if getattr(p, "holder", p.pid) != p.pid:
        with contextlib.suppress(OSError):
            os.kill(p.holder, signal.SIGTERM)
    p.kill()
    p.wait()


def _stranger(not_started: str, new_session: bool):
    """A live process that is not the holder: same group as the holder unless new_session, never its start time."""
    for _ in range(5):
        q = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=new_session)
        if proc_identity.started(q.pid) != not_started:
            return q
        _kill(q)
        time.sleep(1.0)
    raise AssertionError("no process started in a second other than the holder's")


def test_a_lease_records_its_holders_group_and_start_time():
    p = _holder()
    try:
        h = _row_of(p.holder)
        assert h["pgid"] == (os.getpgid(p.holder) if sys.platform != "win32" else None)
        assert h["started"] == proc_identity.started(p.holder) != ""
        assert exclusive.state_of(h) == exclusive.LOADING
    finally:
        _kill(p)


@pytest.mark.parametrize("new_session", [False, True], ids=["same-group", "other-group"])
def test_a_reused_pid_does_not_keep_a_lapsed_lease_alive(new_session):
    p = _holder()
    h = _row_of(p.holder)
    _kill(p)
    q = _stranger(h["started"], new_session)
    try:
        # The SIGKILLed holder's pid now names q: what a reused pid looks like to the row.
        h = _set(h["id"], pid=q.pid, expires_at=time.time() - 1)
        assert exclusive.state_of(h) == exclusive.ABANDONED
        conn = ms.connect()
        try:
            assert exclusive._lapsed(conn, time.time()) == []
        finally:
            conn.close()
        with exclusive.gpu_now("image") as got:
            assert got, "a lease whose holder is gone must not hold the GPU"
        conn = ms.connect()
        try:
            assert item_lease.row(conn, h["id"])["released_at"] is not None
        finally:
            conn.close()
        assert q.poll() is None, "the stranger is never signalled"
    finally:
        _kill(q)


def test_a_lapsed_lease_whose_holder_died_frees_the_gpu():
    p = _holder()
    h = _row_of(p.holder)
    _kill(p)
    h = _set(h["id"], expires_at=time.time() - 1)
    assert exclusive.state_of(h) == exclusive.ABANDONED
    with exclusive.gpu_now("image") as got:
        assert got
    conn = ms.connect()
    try:
        assert item_lease.row(conn, h["id"])["released_at"] is not None, "reaped through _move, not left behind"
    finally:
        conn.close()


def test_the_wait_for_the_gpu_ends_at_its_bound_with_one_alert():
    p = _holder(seconds=300)
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(REPO)!r})
        from harness import exclusive
        try:
            with exclusive.held("video", poll=0.1, wait_s=1.0):
                print("held")
        except exclusive.WaitExpired as exc:
            print("expired:", exc)
    """)
    try:
        got = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=90,
                             env={**os.environ, exclusive.HELD_ENV: ""})
        assert got.returncode == 0, got.stderr
        assert got.stdout.startswith("expired: video gave up waiting for the GPU after 1s (gpu_wait)"), got.stdout
        assert f"pid {p.holder}" in got.stdout, "the outcome names what it waited behind"
        lines = [json.loads(x) for x in monitor.alerts_path().read_text(encoding="utf-8").splitlines()]
        assert [x["kind"] for x in lines] == ["gpu-refused"] and "gave up waiting" in json.dumps(lines[0])
        assert p.poll() is None and exclusive.state_of(_row_of(p.holder)) == exclusive.LOADING
    finally:
        _kill(p)
