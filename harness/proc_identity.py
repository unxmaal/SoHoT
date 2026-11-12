"""A process's identity, pid with its group and start time, so a reused pid is never taken for the process that held it. #1772."""
from __future__ import annotations

import contextlib
import os
import struct
import sys
from pathlib import Path

#: struct kinfo_proc on macOS: its size, the offset of p_stat, and p_stat's zombie value. FINDING #773.
_KINFO_SIZE, _KINFO_P_STAT, _SZOMB = 648, 36, 5


def _darwin(pid: int) -> tuple[str, bool] | None:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    mib = (ctypes.c_int * 4)(1, 14, 1, int(pid))  # CTL_KERN, KERN_PROC, KERN_PROC_PID
    buf = ctypes.create_string_buffer(_KINFO_SIZE)
    size = ctypes.c_size_t(_KINFO_SIZE)
    if libc.sysctl(mib, 4, buf, ctypes.byref(size), None, 0) or size.value < _KINFO_P_STAT + 1:
        return None
    sec, usec = struct.unpack_from("qi", buf.raw, 0)
    return f"{sec}.{usec:06d}", buf.raw[_KINFO_P_STAT] == _SZOMB


def _linux(pid: int) -> tuple[str, bool] | None:
    fields = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
    return fields[19], fields[0] == "Z"


def _proc(pid: int) -> tuple[str, bool] | None:
    """(start time as the OS keeps it, zombie) for pid; None when it is gone or this OS cannot say."""
    try:
        if sys.platform == "darwin":
            return _darwin(pid)
        if sys.platform.startswith("linux"):
            return _linux(pid)
    except (OSError, ValueError, IndexError):
        return None
    return None


def started(pid: int) -> str:
    """When pid started, '' when unknown."""
    got = _proc(pid)
    return got[0] if got else ""


def identity(pid: int) -> dict:
    """pid, its group (None where there are none) and its start time ('' when unknown)."""
    pgid = None
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            pgid = os.getpgid(int(pid))
    return {"pid": int(pid), "pgid": pgid, "started": started(pid)}


def same(rec: dict) -> bool | None:
    """Whether the process a record names is still the one recorded (pid, group, start time, not a zombie); None when it cannot say."""
    if sys.platform == "win32" or not rec.get("pid"):
        return None
    try:
        group = os.getpgid(int(rec["pid"]))
    except ProcessLookupError:
        return False
    except OSError:
        return None
    if rec.get("pgid") is not None and group != int(rec["pgid"]):
        return False
    if not rec.get("started"):
        return None
    got = _proc(int(rec["pid"]))
    if got is None:
        return None  # the pid exists; an unread start time cannot say it is another process. #1836
    return got[0] == rec["started"] and not got[1]
