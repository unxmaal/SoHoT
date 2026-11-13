"""A process's identity, pid with its group and start time, so a reused pid is never taken for the process that held it. #1772."""
from __future__ import annotations

import contextlib
import errno
import functools
import os
import struct
import sys
from pathlib import Path

#: struct kinfo_proc on macOS: its size, the offset of p_stat, and p_stat's zombie value. FINDING #773.
_KINFO_SIZE, _KINFO_P_STAT, _SZOMB = 648, 36, 5
#: OpenProcess's PROCESS_QUERY_LIMITED_INFORMATION, its ERROR_INVALID_PARAMETER for no such pid, and a running process's exit code.
_QUERY_LIMITED, _NO_SUCH_PID, _STILL_ACTIVE = 0x1000, 87, 259
#: FILETIME (100 ns since 1601) at the Unix epoch.
_FILETIME_EPOCH = 116444736000000000


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


@functools.lru_cache(maxsize=1)
def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.GetProcessTimes.argtypes = (wintypes.HANDLE, *[wintypes.LPFILETIME] * 4)
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, wintypes.LPDWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k


def _win32_open(pid: int):
    """A handle to query pid by; ProcessLookupError when no process has it, another OSError when Windows refuses."""
    import ctypes
    handle = _kernel32().OpenProcess(_QUERY_LIMITED, False, int(pid))
    if handle:
        return handle
    err = ctypes.get_last_error()  # type: ignore[attr-defined]
    if err == _NO_SUCH_PID:
        raise ProcessLookupError(errno.ESRCH, f"no process {int(pid)}")
    raise getattr(ctypes, "WinError")(err)


def _win32(pid: int) -> tuple[str, bool]:
    """(creation FILETIME, exited): an exited process whose handle is still open is a zombie here."""
    import ctypes
    from ctypes import wintypes
    k, handle = _kernel32(), _win32_open(pid)
    times, code = [wintypes.FILETIME() for _ in range(4)], wintypes.DWORD()
    try:
        if not (k.GetProcessTimes(handle, *map(ctypes.byref, times)) and
                k.GetExitCodeProcess(handle, ctypes.byref(code))):
            raise getattr(ctypes, "WinError")(ctypes.get_last_error())  # type: ignore[attr-defined]
    finally:
        k.CloseHandle(handle)
    return str(times[0].dwHighDateTime << 32 | times[0].dwLowDateTime), code.value != _STILL_ACTIVE


def _proc(pid: int) -> tuple[str, bool] | None:
    """(start time as the OS keeps it, zombie) for pid; None when it is gone or this OS cannot say."""
    try:
        if sys.platform == "darwin":
            return _darwin(pid)
        if sys.platform.startswith("linux"):
            return _linux(pid)
        if sys.platform == "win32":
            return _win32(pid)
    except (OSError, ValueError, IndexError):
        return None
    return None


def started(pid: int) -> str:
    """When pid started, '' when unknown."""
    got = _proc(pid)
    return got[0] if got else ""


def _boot_epoch() -> float:
    for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
        if line.startswith("btime "):
            return float(line.split()[1])
    raise ValueError("/proc/stat has no btime")


def began(pid: int) -> float | None:
    """When pid started, in seconds since the epoch; None when it is gone or this OS cannot say."""
    got = _proc(pid)
    if got is None:
        return None
    if sys.platform == "darwin":
        return float(got[0])
    if sys.platform == "win32":
        return (int(got[0]) - _FILETIME_EPOCH) / 1e7
    try:
        return _boot_epoch() + int(got[0]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError):
        return None


def identity(pid: int) -> dict:
    """pid, its group (None where there are none) and its start time ('' when unknown)."""
    pgid = None
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            pgid = os.getpgid(int(pid))
    return {"pid": int(pid), "pgid": pgid, "started": started(pid)}


def _group(pid: int) -> int | None:
    """pid's process group, None where there are none; ProcessLookupError when no process has pid."""
    if sys.platform == "win32":
        _kernel32().CloseHandle(_win32_open(pid))
        return None
    return os.getpgid(pid)


def same(rec: dict) -> bool | None:
    """Whether the process a record names is still the one recorded (pid, group, start time, not a zombie); None when it cannot say."""
    if not rec.get("pid"):
        return None
    try:
        group = _group(int(rec["pid"]))
    except ProcessLookupError:
        return False
    except OSError:
        return None
    if group is not None and rec.get("pgid") is not None and group != int(rec["pgid"]):
        return False
    if not rec.get("started"):
        return None
    got = _proc(int(rec["pid"]))
    if got is None:
        return None  # the pid exists; an unread start time cannot say it is another process. #1836
    return got[0] == rec["started"] and not got[1]
