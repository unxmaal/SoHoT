"""Stop and start everything that reads the models volume, and measure a disk's read speed. #612."""
from __future__ import annotations

import json
import mmap
import os
import plistlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from harness import env, paths

PREFIX = "com.unxmaal.localharness"
#: Services that load weights from the volume on demand, stopped even when idle.
READERS = ("mlx", "eval", "tts", "discover")
STATE = "volume-stopped.json"
SPEEDS = "disk-speed.jsonl"


class VolumeError(RuntimeError):
    pass


def _default_quiesce() -> bool:
    from harness import workqueue
    return workqueue.quiesce()


def _default_resume() -> None:
    from harness import workqueue
    workqueue.resume()


@dataclass
class Ops:
    run: Callable = field(default=lambda argv, **kw: subprocess.run(
        argv, capture_output=True, text=True, **kw))
    quiesce: Callable = _default_quiesce
    resume: Callable = _default_resume
    ismount: Callable = os.path.ismount
    sleep: Callable = time.sleep


def default_ops() -> Ops:
    return Ops()


def state_path() -> Path:
    return paths.home() / STATE


def speed_log() -> Path:
    return paths.home() / SPEEDS


def volume_of(path: str) -> str:
    """/Volumes/<name> for a path under it, mounted or not; else the mount point above it."""
    p = Path(os.path.abspath(path))
    if len(p.parts) >= 3 and p.parts[1] == "Volumes":
        return str(Path(*p.parts[:3]))
    p = p.resolve()
    while not os.path.ismount(p) and p != p.parent:
        p = p.parent
    return str(p)


def default_volume() -> str:
    vol = volume_of(env.configured())
    if Path(vol) == Path(vol).parent:
        raise VolumeError(f"the weights root {env.configured()} is on the root "
                          f"filesystem, not a separate volume; pass --path")
    return vol


def parse_lsof(text: str) -> list[tuple[int, str, str]]:
    result: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str, str]] = set()
    pid, command = None, ""
    for line in text.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            pid, command = int(value), ""
        elif tag == "c":
            command = value
        elif tag == "n" and pid is not None:
            key = (pid, command, value)
            if key not in seen:
                seen.add(key)
                result.append(key)
    return result


def parse_ps(text: str) -> dict[int, int]:
    result: dict[int, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            result[int(parts[0])] = int(parts[1])
        except ValueError:
            continue
    return result


def owner(pid: int, parents: dict[int, int], roots: dict[int, str]) -> str | None:
    seen: set[int] = set()
    cur = pid
    while cur not in seen:
        if cur in roots:
            return roots[cur]
        if cur in (0, 1) or cur not in parents:
            return None
        seen.add(cur)
        cur = parents[cur]
    return None


def loaded(ops: Ops) -> dict[str, int | None]:
    """This project's launchd labels that are loaded, with their pid (None when not running)."""
    got = {}
    for line in ops.run(["launchctl", "list"]).stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2].startswith(PREFIX + "."):
            got[parts[2]] = int(parts[0]) if parts[0].isdigit() else None
    return got


def holders(vol: str, ops: Ops) -> list[tuple[int, str, str]]:
    """Every process with a file open on the volume; lsof on a mount point lists the whole filesystem."""
    got = ops.run(["lsof", "-F", "pcn", vol])
    if got.returncode not in (0, 1):
        raise VolumeError(f"lsof failed on {vol}: {got.stderr.strip()}")
    own = os.getpid()
    return [h for h in parse_lsof(got.stdout)
            if h[0] != own and (h[2] == vol or h[2].startswith(vol.rstrip("/") + "/"))]


def holding_services(vol: str, ops: Ops, units: dict | None = None) -> tuple[set, list]:
    units = loaded(ops) if units is None else units
    found = holders(vol, ops)
    parents = parse_ps(ops.run(["ps", "-axo", "pid=,ppid="]).stdout)
    roots = {pid: label for label, pid in units.items() if pid}
    return {owner(h[0], parents, roots) for h in found} - {None}, found


def _domain() -> str:
    return f"gui/{os.getuid()}" if sys.platform == "darwin" else "gui/0"


def _await_unload(label: str, ops: Ops, tries: int = 50) -> bool:
    for _ in range(tries):
        if ops.run(["launchctl", "print", f"{_domain()}/{label}"]).returncode != 0:
            return True
        ops.sleep(0.2)
    return False


def stop(vol: str, ops: Ops) -> dict:
    """Quiesce the queue, boot out every service that reads the volume, then check lsof. #612."""
    if state_path().exists():
        raise VolumeError(f"{state_path()} already records a stop; run `soh volume start` first")
    was_paused = ops.quiesce()
    units = loaded(ops)
    held, _ = holding_services(vol, ops, units)
    wanted = held | {f"{PREFIX}.{s}" for s in READERS}
    targets = sorted(label for label in units if label in wanted)
    stopped = []
    for label in targets:
        ops.run(["launchctl", "bootout", f"{_domain()}/{label}"])
        _await_unload(label, ops)
        stopped.append(label)
        _save(vol, stopped, was_paused)
    _save(vol, stopped, was_paused)
    return {"volume": vol, "stopped": stopped, "was_paused": was_paused,
            "remaining": holders(vol, ops)}


def _save(vol: str, stopped: list, was_paused: bool) -> None:
    state_path().write_text(json.dumps(
        {"volume": vol, "stopped": stopped, "was_paused": was_paused,
         "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1), encoding="utf-8")


def start(ops: Ops) -> dict:
    """Bring back exactly what stop stopped; resume the queue only if it was running. #612."""
    if not state_path().exists():
        raise VolumeError(f"nothing to start: no {state_path().name} from `soh volume stop`")
    saved = json.loads(state_path().read_text(encoding="utf-8"))
    vol = saved["volume"]
    if not ops.ismount(vol):
        raise VolumeError(f"{vol} is not mounted; mount it, then run `soh volume start`")
    agents = Path.home() / "Library" / "LaunchAgents"
    started, failed = [], []
    for label in saved["stopped"]:
        got = ops.run(["launchctl", "bootstrap", _domain(), str(agents / f"{label}.plist")])
        (started if got.returncode == 0 else failed).append(label)
    if failed:
        raise VolumeError("could not load " + ", ".join(failed)
                          + f"; {state_path()} is kept, fix and re-run")
    if not saved["was_paused"]:
        ops.resume()
    state_path().unlink()
    return {"volume": vol, "started": started, "resumed": not saved["was_paused"]}


def status(vol: str, ops: Ops) -> dict:
    mounted = bool(ops.ismount(vol))
    services, found = holding_services(vol, ops) if mounted else (set(), [])
    pending = json.loads(state_path().read_text(encoding="utf-8")) if state_path().exists() else None
    return {"volume": vol, "mounted": mounted, "services": sorted(services),
            "holders": [{"pid": p, "command": c, "path": n} for p, c, n in found],
            "stopped": pending}


def _free(path: str) -> int:
    return shutil.disk_usage(path).free


def _nocache(fd: int) -> str:
    """Turn the page cache off for this fd where the platform can; name what was done."""
    try:
        import fcntl
    except ImportError:
        return "buffered (may be cached)"
    if hasattr(fcntl, "F_NOCACHE"):
        fcntl.fcntl(fd, fcntl.F_NOCACHE, 1)
        return "F_NOCACHE"
    if hasattr(os, "posix_fadvise"):
        return "fadvise DONTNEED"
    return "buffered (may be cached)"


def _drop(fd: int, method: str) -> None:
    if method == "fadvise DONTNEED":
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)


def describe(vol: str, run=None) -> dict:
    """Which device and bus the volume is on, so a before and after are told apart."""
    run = run or Ops().run
    try:
        got = run(["diskutil", "info", "-plist", vol])
        info = plistlib.loads(got.stdout.encode()) if got.returncode == 0 else {}
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {}
    return {k: info[k] for k in ("DeviceIdentifier", "BusProtocol", "MediaName",
                                 "FilesystemType") if k in info}


def speed(path: str, size: int = 2560 * 1024 * 1024, block: int = 8 * 1024 * 1024,
          run=None) -> dict:
    """Write a scratch file and read it back uncached, sequentially; store the row. #612."""
    if _free(path) < size + 1024 ** 3:
        raise VolumeError(f"{path} has under {size // 1024 ** 2} MiB + 1 GiB free")
    block = min(block, size)
    scratch = Path(path) / f".soh-disk-speed-{os.getpid()}"
    buf = mmap.mmap(-1, block)  # page-aligned: F_NOCACHE bypasses the cache only for aligned I/O
    buf.write(os.urandom(block))
    try:
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0))
        try:
            method = _nocache(fd)
            t0 = time.perf_counter()
            for _ in range(size // block):
                os.write(fd, buf)
            os.fsync(fd)
            write_s = time.perf_counter() - t0
            _drop(fd, method)
        finally:
            os.close(fd)
        fd = os.open(scratch, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            _nocache(fd)
            _drop(fd, method)
            got, t0 = 0, time.perf_counter()
            while n := os.readv(fd, [buf]):
                got += n
            read_s = time.perf_counter() - t0
        finally:
            os.close(fd)
    finally:
        scratch.unlink(missing_ok=True)
    vol = volume_of(path)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "volume": vol, "path": str(path),
           "bytes": got, "block": block, "method": f"write then sequential read, {method}",
           "read_s": round(read_s, 3), "write_s": round(write_s, 3),
           "read_bytes_per_s": int(got / read_s) if read_s else 0,
           "write_bytes_per_s": int(got / write_s) if write_s else 0,
           "device": describe(vol, run)}
    with speed_log().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row
