"""A reap after a kill is bounded: a child that outlives it is named with its state, the cut recorded, the caller goes on (#1925)."""
import contextlib
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from harness import cuts, executors, job_procs, owned, reaping

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="SIGSTOP and process groups are POSIX")

SLEEPER = [sys.executable, "-c", "import time; time.sleep(300)"]
BOUND = 0.3


class Stuck:
    """A child no signal ends, as one in an uninterruptible kernel wait: every bounded wait times out."""

    def __init__(self, pid=None):
        self.pid, self.returncode, self.killed = pid or os.getpid(), None, 0

    def poll(self):
        return None

    def kill(self):
        self.killed += 1

    def wait(self, timeout=None):
        if timeout is None:
            raise AssertionError("an unbounded wait on a child that never exits")
        time.sleep(timeout)
        raise subprocess.TimeoutExpired("stuck", timeout)


@pytest.fixture
def seen(monkeypatch):
    got = []
    monkeypatch.setattr(reaping, "REAP_TIMEOUT_S", BOUND)
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: got.append((knob, what)))
    return got


def _returns_within(fn, seconds=10.0):
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed back to the test
            box["error"] = exc
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), f"still waiting after {seconds} s"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def test_a_stopped_child_is_named_with_its_state_and_the_cut_recorded(seen, capsys):
    child = subprocess.Popen(SLEEPER)
    try:
        os.kill(child.pid, signal.SIGSTOP)
        assert os.WIFSTOPPED(os.waitpid(child.pid, os.WUNTRACED)[1])
        assert _returns_within(lambda: reaping.wait(child, "a test")) is False
        err = capsys.readouterr().err
        assert f"pid {child.pid} did not exit within {BOUND:g} s" in err and "state T" in err, err
        assert seen == [("reap_after_kill", f"a test: pid {child.pid} not reaped")]
    finally:
        child.kill()
        child.wait()


def test_a_child_that_exits_is_reaped_and_nothing_is_cut(seen):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    assert reaping.wait(child, "a test", timeout=60.0) is True and child.returncode == 0
    assert seen == []


@pytest.mark.parametrize("how", ["stop", "stop_all"])
def test_owned_stop_returns_at_the_bound_naming_a_child_its_kill_did_not_end(how, seen, monkeypatch, capsys):
    monkeypatch.setattr(owned, "_signal", lambda proc, hard: None)
    box = {}

    def start_then_stop():
        # Started and stopped on one thread, as vllm.served does: a TERM guard set on main is undone only from main.
        box["proc"] = owned.start(SLEEPER)
        return owned.stop(box["proc"], grace=0.1) if how == "stop" else owned.stop_all(grace=0.1)
    try:
        _returns_within(start_then_stop)
        proc = box["proc"]
        assert f"owned.{how}: pid {proc.pid} did not exit" in capsys.readouterr().err
        assert seen == [("reap_after_kill", f"owned.{how}: pid {proc.pid} not reaped")]
        assert proc.pid not in owned._children and not list(owned.root().glob("*.json"))
    finally:
        if "proc" in box:
            with contextlib.suppress(OSError):
                os.killpg(box["proc"].pid, signal.SIGKILL)
            box["proc"].wait()


def test_a_job_whose_pid_file_failed_is_killed_and_the_error_raised_at_the_bound(seen, monkeypatch):
    child = Stuck()
    monkeypatch.setattr(job_procs, "spawn_group", lambda argv, cwd, stdout, env: child)

    def no_room(path):
        raise OSError("no room for the pid file")
    monkeypatch.setattr(executors, "started_file", no_room)
    with pytest.raises(OSError, match="no room"):
        _returns_within(lambda: executors.Host().run({"id": 79}, ["true"]))
    assert child.killed == 1 and seen and seen[0][0] == "reap_after_kill"
