"""An eval run directory's one state, read from progress.json, its process and its pause and stopped files. #1729."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

# Stdlib only: harness/sweep_guard.py loads this as a file when launchd.sh runs it with python3 -I.
try:
    from harness import proc_identity
except ImportError:  # loaded as a file: proc_identity is the stdlib-only module beside it
    import importlib.util
    _spec = importlib.util.spec_from_file_location("proc_identity", Path(__file__).with_name("proc_identity.py"))
    proc_identity = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(proc_identity)
PROGRESS = "progress.json"
CHECKPOINT = "checkpoint.jsonl"
PAUSE_FILE = "pause"
STOP_FILE = "stopped"
#: Locked by the one evals.run writing the directory, holding its proc_identity. #1740.
WRITER = "writer.lock"

#: What evals.run writes in progress.json's `state`; Progress.write refuses anything else.
W_RUNNING, W_YIELDING, W_PAUSED, W_STOPPED, W_DONE = "running", "yielding", "paused", "stopped", "done"
WRITTEN = (W_RUNNING, W_YIELDING, W_PAUSED, W_STOPPED, W_DONE)
IN_FLIGHT = (W_RUNNING, W_YIELDING)

ABSENT = "absent"
RUNNING = "running"
YIELDING = "yielding"
PAUSING = "pausing"
EXITING = "exiting"
PAUSED = "paused"
STOPPED = "stopped"
DONE = "done"
CRASHED = "crashed"
SIGNALLED = "signalled"
UNKNOWN = "unknown"
#: Every state a run directory can be in. UNKNOWN is any combination the others do not name.
STATES = (ABSENT, RUNNING, YIELDING, PAUSING, EXITING, PAUSED, STOPPED, DONE, CRASHED, SIGNALLED, UNKNOWN)

#: A process may still be writing the directory: a deploy refuses on these.
LIVE = (RUNNING, YIELDING, PAUSING, EXITING, UNKNOWN)
#: The watchdog pauses through these; a pause file is harmless where the process is gone.
PAUSABLE = (RUNNING, YIELDING, PAUSING, UNKNOWN)
#: Its process is gone without a pause recorded: a sweep may resume its checkpoint.
RESUMABLE = (PAUSED, CRASHED, SIGNALLED)


class State(NamedTuple):
    name: str
    written: str
    progress: dict
    why: str


def alive(pid, pgid, started="") -> bool | None:
    """Whether the run's process is the one recorded (pid, group, start time); None when this platform or record cannot say."""
    try:
        pid = int(pid)
        group = int(pgid) if pgid is not None else None
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return _win_alive(pid)
    if started:
        same = proc_identity.same({"pid": pid, "pgid": group, "started": started})
        if same is not None:
            return same
    try:
        # A progress file written before #1843 has no start time. With no group recorded a reused pid cannot be told apart, so it counts as alive.
        return os.getpgid(pid) == group or group is None
    except ProcessLookupError:
        return False
    except OSError:
        return None


def _win_alive(pid: int) -> bool | None:
    import ctypes
    try:
        kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return None
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return True if ctypes.get_last_error() == 5 else False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _reason(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip().partition(" ")[2].strip()
    except (OSError, ValueError):
        return ""


def of(outdir, alive=alive) -> State:
    """The one state of the run in `outdir`; `alive(pid, pgid, started)` is True, False or None (cannot say)."""
    out = Path(outdir)
    try:
        raw = (out / PROGRESS).read_text(encoding="utf-8")
    except FileNotFoundError:
        if (out / CHECKPOINT).is_file():
            return State(UNKNOWN, "", {}, "a checkpoint with no progress file")
        return State(ABSENT, "", {}, "")
    except OSError as exc:
        return State(UNKNOWN, "", {}, f"progress file unreadable: {exc}")
    try:
        got = json.loads(raw)
    except ValueError:
        got = None
    if not isinstance(got, dict):
        return State(UNKNOWN, "", {}, "progress file is not a JSON object")
    written = got.get("state")
    written = written if isinstance(written, str) else ""
    if written not in WRITTEN:
        return State(UNKNOWN, written, got, f"progress state {written!r} is none evals.run writes")
    live = alive(got.get("pid"), got.get("pgid"), str(got.get("pid_started") or ""))
    if written in IN_FLIGHT:
        if live is None:
            return State(UNKNOWN, written, got, "its process cannot be told alive or gone")
        if live:
            if (out / PAUSE_FILE).exists():
                return State(PAUSING, written, got, _reason(out / PAUSE_FILE))
            return State(YIELDING if written == W_YIELDING else RUNNING, written, got, "")
        if (out / STOP_FILE).exists():
            return State(SIGNALLED, written, got, _reason(out / STOP_FILE))
        return State(CRASHED, written, got, "")
    if live:
        return State(EXITING, written, got, str(got.get("why") or ""))
    return State({W_PAUSED: PAUSED, W_STOPPED: STOPPED, W_DONE: DONE}[written], written, got,
                 str(got.get("why") or ""))
