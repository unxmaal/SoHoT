"""Which of this user's live processes run from a directory: cwd, executable, open or mapped file under it. #1523."""
from __future__ import annotations

import ctypes
import ctypes.util
import functools
import os
import sys
from pathlib import Path

# <sys/proc_info.h>: struct vnode_info is 152 bytes, then the MAXPATHLEN path of a vnode_info_path.
_VI, _PATH = 152, 1024
_VIP = _VI + _PATH
PIDLISTFDS, PIDVNODEPATHINFO, PIDREGIONPATHINFO2, PIDFDVNODEPATHINFO = 1, 9, 22, 2
FDTYPE_VNODE = 1
_FILEINFO = 24
_REGIONINFO = 96


@functools.lru_cache(maxsize=1)
def _libproc():
    lib = ctypes.CDLL(ctypes.util.find_library("proc") or "libproc.dylib", use_errno=True)
    lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidfdinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_name.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    return lib


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", "surrogateescape")


def _darwin_pids(lib) -> list[int]:
    n = lib.proc_listallpids(None, 0)
    buf = (ctypes.c_int * (max(n, 0) + 256))()
    got = lib.proc_listallpids(buf, ctypes.sizeof(buf))
    return [buf[i] for i in range(max(got, 0)) if buf[i] > 0]


def _darwin_paths(lib, pid: int):
    """(how, path) for each place pid runs from, cheapest first; nothing for a pid this user cannot read."""
    buf = ctypes.create_string_buffer(2 * _VIP)
    if lib.proc_pidinfo(pid, PIDVNODEPATHINFO, 0, buf, ctypes.sizeof(buf)) != ctypes.sizeof(buf):
        return
    yield "cwd", _cstr(buf.raw[_VI:_VIP])
    exe = ctypes.create_string_buffer(4096)
    if lib.proc_pidpath(pid, exe, ctypes.sizeof(exe)) > 0:
        yield "executable", exe.value.decode("utf-8", "surrogateescape")
    size = lib.proc_pidinfo(pid, PIDLISTFDS, 0, None, 0)
    if size > 0:
        fds = ctypes.create_string_buffer(size + 64 * 8)
        got = lib.proc_pidinfo(pid, PIDLISTFDS, 0, fds, ctypes.sizeof(fds))
        one = ctypes.create_string_buffer(_FILEINFO + _VIP)
        for i in range(0, max(got, 0) - 7, 8):
            fd = int.from_bytes(fds.raw[i:i + 4], "little", signed=True)
            if int.from_bytes(fds.raw[i + 4:i + 8], "little") != FDTYPE_VNODE:
                continue
            if lib.proc_pidfdinfo(pid, fd, PIDFDVNODEPATHINFO, one, ctypes.sizeof(one)) == ctypes.sizeof(one):
                yield f"open fd {fd}", _cstr(one.raw[_FILEINFO + _VI:])
    region = ctypes.create_string_buffer(_REGIONINFO + _VIP)
    addr = 0
    while lib.proc_pidinfo(pid, PIDREGIONPATHINFO2, addr, region, ctypes.sizeof(region)) == ctypes.sizeof(region):
        start = int.from_bytes(region.raw[80:88], "little")
        yield "mapped file", _cstr(region.raw[_REGIONINFO + _VI:])
        nxt = start + int.from_bytes(region.raw[88:96], "little")
        if nxt <= addr:
            return
        addr = nxt


def _darwin_name(lib, pid: int) -> str:
    buf = ctypes.create_string_buffer(256)
    return buf.value.decode("utf-8", "replace") if lib.proc_name(pid, buf, ctypes.sizeof(buf)) > 0 else "?"


def _linux_paths(pid: int):
    base = f"/proc/{pid}"
    for how, link in (("cwd", "cwd"), ("executable", "exe")):
        try:
            yield how, os.readlink(f"{base}/{link}")
        except OSError:
            if how == "cwd":
                return
    try:
        fds = os.listdir(f"{base}/fd")
    except OSError:
        fds = []
    for fd in fds:
        try:
            yield f"open fd {fd}", os.readlink(f"{base}/fd/{fd}")
        except OSError:
            continue
    try:
        with open(f"{base}/maps", encoding="utf-8", errors="surrogateescape") as fh:
            for line in fh:
                parts = line.split(None, 5)
                if len(parts) == 6 and parts[5].startswith("/"):
                    yield "mapped file", parts[5].rstrip("\n")
    except OSError:
        return


def _linux_name(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip() or "?"
    except OSError:
        return "?"


def _under(path: str, roots: list[str]) -> str:
    for r in roots:
        if path == r or path.startswith(r + "/"):
            return r
    return ""


def holding(dirs) -> dict[Path, list[str]] | None:
    """Each of dirs that a live process runs from -> 'pid N name (how path)' for each; None where nobody can tell."""
    platform = sys.platform
    roots: dict[str, list[Path]] = {}
    for d in dirs:
        roots.setdefault(os.path.realpath(d), []).append(Path(d))
    if not roots:
        return {}
    if platform == "darwin":
        try:
            lib = _libproc()
        except OSError:
            return None
        pids, paths, name = _darwin_pids(lib), functools.partial(_darwin_paths, lib), functools.partial(_darwin_name, lib)
    elif platform.startswith("linux"):
        pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
        paths, name = _linux_paths, _linux_name
    else:
        return None
    found: dict[Path, list[str]] = {}
    want = sorted(roots)
    for pid in pids:
        seen: set[str] = set()
        for how, path in paths(pid):
            root = _under(path, want)
            if root and root not in seen:
                seen.add(root)
                for d in roots[root]:
                    found.setdefault(d, []).append(f"pid {pid} {name(pid)} ({how} {path})")
                if len(seen) == len(want):
                    break
    return found
