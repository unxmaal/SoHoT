"""stop_group on a group whose leader exited unreaped, and a job that leaves children behind. #677."""
import contextlib
import os
import signal
import subprocess
import sys
import time

import pytest

from harness import exclusive, workqueue as wq

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="a POSIX process group and flock")


@pytest.fixture(autouse=True)
def _no_marker(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)


def _holder(lock, held, on_term="exit"):
    """A grandchild that takes the lock, says so, and sleeps; on TERM it exits, ignores it, or lingers and leaves a mark."""
    react = {"exit": "",
             "ignore": "signal.signal(signal.SIGTERM, signal.SIG_IGN);",
             "linger": ("signal.signal(signal.SIGTERM, lambda *_: (time.sleep(0.5), "
                        f"open({str(held) + '.term'!r}, 'w'), os._exit(0)));")}[on_term]
    return ("import fcntl, os, signal, time;" + react +
            f"f = open({str(lock)!r}, 'w'); fcntl.flock(f, fcntl.LOCK_EX);"
            f"open({str(held)!r}, 'w').write(str(os.getpid())); time.sleep(120)")


def _leader(lock, held, on_term="exit"):
    """A leader that starts the holder, waits until it holds the lock, and exits."""
    return ("import os, subprocess, sys, time;"
            f"subprocess.Popen([sys.executable, '-c', {_holder(lock, held, on_term)!r}], "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL);"
            f"[time.sleep(0.02) for _ in range(1500) if not os.path.exists({str(held)!r})]")


def _spawn_exited(tmp_path, on_term="exit"):
    """A group leader that has exited and is not reaped, with a grandchild holding the lock."""
    lock, held = tmp_path / "lock", tmp_path / "held"
    proc = wq.spawn_group([sys.executable, "-c", _leader(lock, held, on_term)], None,
                          subprocess.PIPE, None)
    proc.stdout.read()
    assert held.exists() and held.read_text(encoding="utf-8")
    return proc, lock, int(held.read_text(encoding="utf-8"))


def _lock_free(lock) -> bool:
    import fcntl
    with open(lock, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def _cleanup(proc, grandchild):
    with contextlib.suppress(OSError):
        os.kill(grandchild, signal.SIGKILL)
    proc.wait(timeout=30)


def test_a_group_whose_leader_exited_unreaped_is_stopped_without_raising(tmp_path):
    proc, lock, grandchild = _spawn_exited(tmp_path)
    try:
        assert not _lock_free(lock)
        started = time.monotonic()
        assert wq.stop_group(proc.pid, grace=10.0) == "term"
        assert time.monotonic() - started < 5.0
        assert _lock_free(lock)
    finally:
        _cleanup(proc, grandchild)


def test_the_caller_s_own_leader_is_reaped_while_its_group_stops(tmp_path):
    proc, lock, grandchild = _spawn_exited(tmp_path)
    try:
        assert wq.stop_group(proc.pid, grace=10.0, proc=proc) == "term"
        assert proc.returncode is not None
        assert _lock_free(lock)
        assert wq.stop_group(proc.pid, grace=10.0, proc=proc) == "gone"
    finally:
        _cleanup(proc, grandchild)


def test_a_grandchild_that_ignores_term_is_killed_after_the_grace(tmp_path):
    proc, lock, grandchild = _spawn_exited(tmp_path, on_term="ignore")
    try:
        assert wq.stop_group(proc.pid, grace=1.0) == "kill"
        deadline = time.monotonic() + 10
        while not _lock_free(lock) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _lock_free(lock)
    finally:
        _cleanup(proc, grandchild)


def test_measure_gives_the_grandchildren_the_grace_not_only_the_leader(tmp_path):
    from harness.commands import measure
    lock, held = tmp_path / "lock", tmp_path / "held"
    proc = subprocess.Popen([sys.executable, "-c", _leader(lock, held, "linger") + "; time.sleep(120)"],
                            start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while not held.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        measure._stop_group(proc, 10.0)
        assert proc.returncode is not None
        assert (tmp_path / "held.term").exists()
        assert _lock_free(lock)
    finally:
        proc.kill()
        proc.wait(timeout=30)


def test_a_job_that_leaves_a_child_holding_the_lock_does_not_keep_it(tmp_path):
    lock, held = tmp_path / "lock", tmp_path / "held"
    job = wq.add([sys.executable, "-c", _leader(lock, held)], title="leaves a child")
    wq.run_pending()
    grandchild = int(held.read_text(encoding="utf-8"))
    try:
        assert _lock_free(lock)
        assert wq.get(job["id"])["state"] == wq.DONE
        log = (wq.log_dir() / f"{job['id']}.log").read_text(encoding="utf-8")
        assert "left running" in log
    finally:
        with contextlib.suppress(OSError):
            os.kill(grandchild, signal.SIGKILL)


def _stat(root, pid, state, pgid):
    d = root / str(pid)
    d.mkdir()
    (d / "stat").write_text(f"{pid} (a (b) c) {state} 1 {pgid} {pgid} 0", encoding="utf-8")


def test_linux_reads_a_group_of_zombies_as_stopped(tmp_path):
    _stat(tmp_path, 10, "Z", 10)
    _stat(tmp_path, 11, "S", 99)
    (tmp_path / "self").mkdir()
    assert wq._live_member(10, proc_root=tmp_path) is False
    _stat(tmp_path, 12, "S", 10)
    assert wq._live_member(10, proc_root=tmp_path) is True
    assert wq._live_member(55, proc_root=tmp_path) is True


def test_macos_reads_a_member_inside_exit_as_alive():
    assert wq._exiting_member(10, read=lambda pgid: [wq._SZOMB, wq._SZOMB]) is False
    assert wq._exiting_member(10, read=lambda pgid: []) is False
    assert wq._exiting_member(10, read=lambda pgid: [wq._SZOMB, 2]) is True
    assert wq._exiting_member(10, read=lambda pgid: None) is True


@pytest.mark.parametrize("refused", [signal.SIGTERM, 0])
def test_stop_group_waits_for_a_member_still_inside_exit_after_eperm(monkeypatch, refused):
    states = [[2, wq._SZOMB]] * 3 + [[wq._SZOMB, wq._SZOMB]]
    reads, sent = [], []

    def killpg(pid, sig):
        sent.append(sig)
        if len(sent) > 1 and (sig == refused or sig == 0):
            raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(wq.sys, "platform", "darwin")
    monkeypatch.setattr(wq.os, "killpg", killpg)
    real = wq._exiting_member
    monkeypatch.setattr(wq, "_exiting_member", lambda pgid: real(
        pgid, read=lambda g: reads.append(g) or states[len(reads) - 1]))
    assert wq.stop_group(77, grace=10.0, sleep=lambda s: None) == "term"
    assert len(reads) == len(states)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sysctl KERN_PROC_PGRP")
def test_macos_reads_a_real_group_s_states_until_its_member_is_a_zombie():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    try:
        states = wq._pgrp_states(proc.pid)
        assert states and wq._SZOMB not in states
        os.kill(proc.pid, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while wq._pgrp_states(proc.pid) != [wq._SZOMB] and time.monotonic() < deadline:
            time.sleep(0.02)
        assert wq._pgrp_states(proc.pid) == [wq._SZOMB]
        assert wq._exiting_member(proc.pid) is False
    finally:
        proc.kill()
        proc.wait(timeout=30)
    assert wq._pgrp_states(proc.pid) == []
