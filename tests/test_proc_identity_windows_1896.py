"""On Windows a process's identity is its creation time from GetProcessTimes, so a dead or reused pid is told apart there too. #1896."""
import gc
import os
import subprocess
import sys
import time
import types

import pytest

from harness import proc_identity

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="the real kernel32 calls")
MADE = "133700000000000000"


@pytest.fixture()
def win32(monkeypatch):
    """sys.platform reads win32 and kernel32 answers what each test sets: a handle, or the error OpenProcess gives."""
    closed, told = [], {"open": 7, "proc": (MADE, False)}

    def open_(pid):
        if isinstance(told["open"], BaseException):
            raise told["open"]
        return told["open"]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(proc_identity, "_kernel32", lambda: types.SimpleNamespace(CloseHandle=closed.append))
    monkeypatch.setattr(proc_identity, "_win32_open", open_)
    monkeypatch.setattr(proc_identity, "_win32", lambda pid: (open_(pid), told["proc"])[1])
    told["closed"] = closed
    return told


def test_a_live_process_with_the_recorded_creation_time_is_the_same_one_and_its_handle_is_closed(win32):
    assert proc_identity.identity(42) == {"pid": 42, "pgid": None, "started": MADE}
    assert proc_identity.same({"pid": 42, "pgid": None, "started": MADE}) is True
    assert win32["closed"] == [7]


def test_a_recorded_group_is_not_compared_where_there_are_none(win32):
    assert proc_identity.same({"pid": 42, "pgid": 42, "started": MADE}) is True


def test_a_reused_pid_is_another_process(win32):
    assert proc_identity.same({"pid": 42, "pgid": None, "started": "133600000000000000"}) is False


def test_an_exited_process_whose_handle_is_still_open_is_dead_like_a_zombie(win32):
    win32["proc"] = (MADE, True)
    assert proc_identity.same({"pid": 42, "pgid": None, "started": MADE}) is False


def test_a_pid_no_process_has_is_gone_even_without_a_start_time(win32):
    win32["open"] = ProcessLookupError()
    assert proc_identity.same({"pid": 42, "pgid": None, "started": MADE}) is False
    assert proc_identity.same({"pid": 42, "pgid": None, "started": ""}) is False


def test_a_process_windows_will_not_open_cannot_be_judged(win32):
    win32["open"] = PermissionError(13, "Access is denied")
    assert proc_identity.same({"pid": 42, "pgid": None, "started": MADE}) is None
    assert proc_identity.started(42) == ""


def test_a_live_pid_with_no_recorded_start_time_cannot_be_judged(win32):
    assert proc_identity.same({"pid": 42, "pgid": None, "started": ""}) is None


def test_a_creation_filetime_is_read_as_seconds_since_the_epoch(win32, monkeypatch):
    monkeypatch.setattr(proc_identity, "_win32", lambda pid: ("116444736000000000", False))
    assert proc_identity.began(42) == 0.0
    monkeypatch.setattr(proc_identity, "_win32", lambda pid: (str(116444736000000000 + 15 * 10**7), False))
    assert proc_identity.began(42) == 15.0


@WINDOWS
def test_kernel32_reads_this_process_and_a_child_started_now():
    me = proc_identity.identity(os.getpid())
    assert me["pgid"] is None and me["started"].isdigit() and proc_identity.same(me) is True
    before = time.time()
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert before - 5 <= proc_identity.began(p.pid) <= time.time() + 5
        assert proc_identity.same(proc_identity.identity(p.pid)) is True
    finally:
        p.kill()
        p.wait()


@WINDOWS
def test_kernel32_calls_a_child_dead_while_its_handle_is_open_and_after_it_closes():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    rec = proc_identity.identity(p.pid)
    assert rec["started"]
    p.wait()
    assert proc_identity.same(rec) is False
    del p
    gc.collect()
    assert proc_identity.same(rec) is False
