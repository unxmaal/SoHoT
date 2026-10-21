"""A rate-capped download and its nettop do not outlive a SIGKILLed controller; what one left is cleared. #1092."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import day_fetch, throttle

ROOT = Path(__file__).resolve().parents[1]
#: Seconds the guard has to continue and end both: the issue's live check allows the same.
BOUND = 10.0

CONTROLLER = r"""
import subprocess, time
from harness import throttle
child = subprocess.Popen(["sleep", "300"])
monitor = throttle.Received(child.pid)
print(child.pid, monitor._proc.pid, flush=True)
seen = [0]
def read(wait):
    time.sleep(min(wait, 0.05))
    seen[0] += 10 ** 9
    return seen[0]
throttle.hold(child, 1.0, read)
"""


def _ps(pid: int) -> tuple[str, str]:
    got = subprocess.run(["ps", "-o", "stat=,command=", "-p", str(pid)], capture_output=True, text=True,
                         check=False).stdout.strip()
    stat, _, cmd = got.partition(" ")
    return stat, cmd.strip()


def _alive(pid: int) -> bool:
    stat, _ = _ps(pid)
    return bool(stat) and not stat.startswith("Z")


def _until(cond, bound: float) -> bool:
    end = time.monotonic() + bound
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


@pytest.mark.skipif(sys.platform != "darwin" or not throttle.available(), reason="the cap holds a download only where nettop counts its bytes")
def test_a_sigkilled_controller_leaves_no_stopped_child_and_no_nettop():
    ctl = subprocess.Popen([sys.executable, "-c", CONTROLLER], cwd=ROOT, stdout=subprocess.PIPE, text=True)
    child, monitor = map(int, ctl.stdout.readline().split())
    try:
        assert _until(lambda: _ps(child)[0].startswith("T"), BOUND), "the controller never stopped its child"
        ctl.kill()
        ctl.wait()
        assert _until(lambda: not _alive(child) and not _alive(monitor), BOUND), \
            f"left behind: child {_ps(child)}, nettop {_ps(monitor)}"
    finally:
        if ctl.poll() is None:
            ctl.kill()
        for pid, mark in ((child, "sleep 300"), (monitor, f"{throttle.NETTOP}{child}")):
            if _alive(pid) and _ps(pid)[1].startswith(mark):
                os.kill(pid, signal.SIGCONT)
                os.kill(pid, signal.SIGKILL)


PS = """\
    1     0 Ss   /sbin/launchd
 2605     1 T    /x/.venv/bin/python -c from huggingface_hub import hf_hub_download
 2606     1 R    nettop -P -x -J bytes_in -p 2605 -L 0 -s 1
 3001     1 Ss   /x/.venv/bin/python -m harness.cli fetch --day
 3002  3001 T    /x/.venv/bin/python -m harness.cli fetch --run --limit 3
 3003  3001 S    nettop -P -x -J bytes_in -p 3002 -L 0 -s 1
 4001     1 T    /x/.venv/bin/python -m harness.cli fetch --run --limit 3
 5001     1 T    vim notes.txt
"""


def test_only_what_a_dead_controller_left_is_a_stray():
    got = dict(throttle.strays(PS))
    assert sorted(got) == [2605, 2606, 4001]
    assert got[2606].startswith("nettop") and got[2605].startswith("stopped download")


@pytest.mark.skipif(sys.platform == "win32", reason="SIGCONT is POSIX")
def test_a_day_fetch_continues_then_ends_each_stray():
    sent = []
    got = day_fetch.clear(throttle.strays(PS), kill=lambda pid, sig: sent.append((pid, sig)))
    assert len(got) == 3 and all("pid" in line for line in got)
    assert sent[:2] == [(2605, signal.SIGCONT), (2605, signal.SIGTERM)]
    assert {pid for pid, _ in sent} == {2605, 2606, 4001}


def test_no_test_sees_this_machines_processes():
    assert throttle.strays() == []
