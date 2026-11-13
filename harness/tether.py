"""A child that dies with its owner: a watcher beside it stops the child once the owner process is gone (#1761)."""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

POLL_S = 0.5
GRACE_S = 10.0

_POPEN = subprocess.Popen

# Stdlib only under python -I: proc_identity is loaded from its file. None from same() is never read as gone.
WATCH = r"""
import importlib.util, json, os, signal, sys, time
spec = importlib.util.spec_from_file_location("proc_identity", sys.argv[1])
pi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pi)
owner, child, poll, grace = json.loads(sys.argv[2]), json.loads(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
signal.signal(signal.SIGINT, signal.SIG_IGN)
while pi.same(owner) is not False:
    if pi.same(child) is False:
        sys.exit(0)
    time.sleep(poll)
for sig in (signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)):
    if pi.same(child) is not True:
        break
    try:
        if child.get("pgid") == child["pid"] and hasattr(os, "killpg"):
            os.killpg(child["pid"], sig)
        else:
            os.kill(child["pid"], sig)
    except OSError:
        break
    end = time.monotonic() + grace
    while pi.same(child) is True and time.monotonic() < end:
        time.sleep(0.05)
"""


def watch_argv(owner: dict, child: dict) -> list[str]:
    from harness import proc_identity
    return [sys.executable, "-I", "-c", WATCH, str(Path(proc_identity.__file__).resolve()),
            json.dumps(owner), json.dumps(child), str(POLL_S), str(GRACE_S)]


def tie(proc) -> subprocess.Popen | None:
    """A watcher that stops proc once this process is gone; None when proc is no real child or its start time is unknown."""
    from harness import proc_identity
    pid = getattr(proc, "pid", None)
    if not isinstance(proc, _POPEN) or not isinstance(pid, int) or pid <= 0:
        return None
    child, owner = proc_identity.identity(pid), proc_identity.identity(os.getpid())
    if not child["started"] or not owner["started"]:
        return None
    return _POPEN(watch_argv(owner, child), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL)


def untie(watcher) -> None:
    """Stop and reap the watcher once its owner has stopped the child itself."""
    if watcher is None:
        return
    with contextlib.suppress(OSError):
        watcher.kill() if hasattr(signal, "SIGKILL") else watcher.terminate()
    watcher.wait()
