"""A child that dies with its owner: a watcher beside it stops the child once the owner process is gone (#1761)."""
from __future__ import annotations

import json
import os
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


# The child ties itself before it runs: it double-forks its watcher (own session, so no group kill takes it), then execs. #1947.
LAUNCH = r"""
import importlib.util, json, os, subprocess, sys
watch, argv = json.loads(sys.argv[1]), sys.argv[3:]
spec = importlib.util.spec_from_file_location("proc_identity", watch[4])
pi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pi)
me = pi.identity(os.getpid())
if me["started"]:
    watch[6] = json.dumps(me)
    if os.fork() == 0:
        try:
            subprocess.Popen(watch, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        finally:
            os._exit(0)
    os.wait()
try:
    os.execvp(argv[0], argv)
except OSError as exc:
    print(f"could not start {argv[0]}: {exc}", file=sys.stderr, flush=True)
    sys.exit(127)
"""


def command(args) -> list:
    """The program a tethered argv runs; any other argv as it is."""
    args = [args] if isinstance(args, (str, bytes)) else list(args)
    if args[:4] == [sys.executable, "-I", "-c", LAUNCH] and args[5:6] == ["--"]:
        return args[6:]
    return args


def _runnable(cmd: list[str], kw: dict) -> bool:
    import shutil
    if os.sep in cmd[0]:
        return os.access(os.path.join(kw.get("cwd") or "", cmd[0]), os.X_OK)
    return shutil.which(cmd[0], path=(kw.get("env") or os.environ).get("PATH")) is not None


def tied(cmd, kw: dict | None = None) -> list[str]:
    """cmd behind LAUNCH, its watcher up before it runs; as it is where exec moves the pid, or Popen would raise anyway."""
    from harness import proc_identity
    cmd = [os.fspath(a) for a in cmd]
    owner = proc_identity.identity(os.getpid())
    if sys.platform == "win32" or not cmd or not owner["started"] or not _runnable(cmd, kw or {}):
        return cmd
    return [sys.executable, "-I", "-c", LAUNCH, json.dumps(watch_argv(owner, {})), "--", *cmd]


def spawn(cmd, popen=None, **kw):
    """popen(cmd, **kw) with the child tied from before it runs; a stand-in popen gets cmd as it is."""
    popen = popen or subprocess.Popen
    if not (isinstance(popen, type) and issubclass(popen, _POPEN)):
        return popen(cmd, **kw)
    if sys.platform != "win32":
        return popen(tied(cmd, kw), **kw)
    proc = popen(cmd, **kw)
    _tie(proc)
    return proc


def _tie(proc) -> subprocess.Popen | None:
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
