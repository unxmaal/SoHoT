"""uv's cache pruned by the disk sweep, never forced (#2049), and its cached environments no process uses removed (#2050)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

LSOF_TIMEOUT_S = 60.0

ENV_MAX_AGE_S = 172800

#: False keeps every cached environment: the disk sweep then only runs `uv cache prune`.
ENV_PRUNE = True

DIR_TIMEOUT_S = 30.0

PRUNE_TIMEOUT_S = 900.0

#: What uv prints first when another uv process holds the cache: it would wait for it, so the prune is skipped.
IN_USE = "Cache is currently in-use"
HELD = "another uv process holds the cache lock (any running `uv run`, this one's parent included); never forced"
_UNITS = {u: 1024 ** i for i, u in enumerate(("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"))}
_REMOVED = re.compile(r"^Removed \d+ (?:files?|director(?:y|ies))(?: \(([\d.]+)\s*([KMGTPE]?i?B)\))?\s*$", re.M)
_NOTHING = re.compile(r"^No unused entries found\s*$", re.M)
_ARCHIVE = re.compile(r"archive-v0/([^/\s]+)")
_LINK = re.compile(r"environments-v2/([^/\s]+)/([^/\s]+)")


def cache_dir(run=None) -> Path | None:
    """The cache `uv cache prune` would prune: UV_CACHE_DIR, else `uv cache dir`; None: no uv; OSError: uv failed."""
    if os.environ.get("UV_CACHE_DIR"):
        return Path(os.environ["UV_CACHE_DIR"])
    uv = shutil.which("uv")
    if not uv:
        return None
    try:
        got = (run or subprocess.run)([uv, "cache", "dir"], capture_output=True, text=True, timeout=DIR_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise OSError(f"`uv cache dir` ran past {DIR_TIMEOUT_S:.0f} s") from exc
    if got.returncode != 0 or not got.stdout.strip():
        raise OSError(f"`uv cache dir` exited {got.returncode}: {(got.stderr or '').strip()[-200:]}")
    return Path(got.stdout.strip())


def held(cache: Path) -> bool | None:
    """Whether a uv process holds `cache`'s lock; None where it cannot be asked (no flock)."""
    if sys.platform == "win32":
        return None
    import fcntl
    lock = cache / ".lock"
    if not lock.exists():
        return False
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def removed_bytes(text: str) -> int | None:
    """The size in uv's `Removed N files (SIZE)` line, 0 when it removed no file; None: no summary uv is known to print."""
    m = _REMOVED.search(text)
    if m:
        return round(float(m.group(1)) * _UNITS[m.group(2)]) if m.group(1) and m.group(2) in _UNITS else 0
    return 0 if _NOTHING.search(text) else None


def prune_at(cache: Path, popen=None) -> dict:
    """`uv cache prune` on `cache`, never --force: {"bytes", "free"}, "bytes" None plus uv's "summary" when unread, or {"skipped": why}."""
    uv = shutil.which("uv")
    if not uv:
        return {"skipped": "no uv on PATH"}
    if not cache.is_dir():
        return {"skipped": f"no uv cache at {cache}"}
    if held(cache):
        return {"skipped": HELD}
    env = {**os.environ, "UV_CACHE_DIR": str(cache), "NO_COLOR": "1"}
    try:
        proc = (popen or subprocess.Popen)([uv, "cache", "prune"], env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    except OSError as exc:
        return {"skipped": f"uv cache prune did not start: {exc}"}
    first = proc.stdout.readline()
    if IN_USE in first:
        proc.kill()
        proc.communicate()
        return {"skipped": HELD}
    late = []
    # Read the rest through the same buffer readline() filled: communicate() reads the raw pipe and loses it (#2056).
    timer = threading.Timer(PRUNE_TIMEOUT_S, lambda: (late.append(True), proc.kill()))
    timer.start()
    try:
        rest = proc.stdout.read()
        proc.wait()
    finally:
        timer.cancel()
    if late:
        return {"skipped": f"uv cache prune ran past {PRUNE_TIMEOUT_S:.0f} s"}
    text = first + (rest or "")
    last = text.strip().splitlines()[-1:]
    if proc.returncode != 0:
        return {"skipped": f"uv cache prune exited {proc.returncode}: {last}"}
    got = {"bytes": removed_bytes(text), "free": shutil.disk_usage(cache).free}
    return got if got["bytes"] is not None else {**got, "summary": last[0] if last else ""}


def prune(popen=None) -> dict:
    """prune_at() on this machine's uv cache; OSError when uv cannot say where that is."""
    cache = cache_dir()
    return prune_at(cache, popen) if cache else {"skipped": "no uv cache to prune"}


def in_use(cache: Path, run=subprocess.run) -> set[str] | None:
    """archive-v0 entries a running process names in its open files (lsof -nP) or args; None when either cannot be read."""
    out = ""
    for cmd in (["lsof", "-nP"], ["ps", "-A", "-ww", "-o", "args="]):
        try:
            got = run(cmd, capture_output=True, text=True, timeout=LSOF_TIMEOUT_S, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if not got.stdout.strip():
            return None
        out += got.stdout
    found = set(_ARCHIVE.findall(out))
    for group, name in _LINK.findall(out):
        target = os.path.realpath(cache / "environments-v2" / group / name)
        if os.path.dirname(target) == os.path.realpath(cache / "archive-v0"):
            found.add(os.path.basename(target))
    return found


def _links(cache: Path) -> dict[str, list[Path]]:
    """archive-v0 entry name -> the environments-v2 links pointing at it."""
    got: dict[str, list[Path]] = {}
    root = cache / "environments-v2"
    for link in root.glob("*/*") if root.is_dir() else ():
        if link.is_symlink():
            got.setdefault(os.path.basename(os.readlink(link)), []).append(link)
    return got


def _size(path: Path) -> int:
    total = 0
    for top, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(top, f)).st_size
            except OSError:
                pass
    return total


def prune_envs_at(cache: Path, now: float | None = None, run=subprocess.run) -> dict:
    """Remove archive-v0 venvs no process uses, older than ENV_MAX_AGE_S, outside uv's lock: {"removed", ...} or {"skipped"}."""
    if not ENV_PRUNE:
        return {"skipped": "ENV_PRUNE is off"}
    archive = cache / "archive-v0"
    if not archive.is_dir():
        return {"skipped": f"no archive-v0 in {cache}"}
    used = in_use(cache, run)
    if used is None:
        return {"skipped": "could not list the processes' open files and args; nothing removed"}
    cut = (time.time() if now is None else now) - ENV_MAX_AGE_S
    links = _links(cache)
    removed, kept_used, fresh, freed = [], [], 0, 0
    for entry in sorted(archive.iterdir()):
        if entry.is_symlink() or not (entry / "pyvenv.cfg").is_file():
            continue
        if entry.name in used:
            kept_used.append(entry.name)
            continue
        mine = links.get(entry.name, [])
        try:
            newest = max([entry.stat().st_mtime] + [os.lstat(link).st_mtime for link in mine])
        except OSError:
            continue
        if newest > cut:
            fresh += 1
            continue
        size = _size(entry)
        shutil.rmtree(entry, ignore_errors=True)
        if entry.exists():
            continue
        for link in mine:
            link.unlink(missing_ok=True)
            try:
                link.parent.rmdir()
            except OSError:
                pass
        removed.append(entry.name)
        freed += size
    if removed:
        from harness import cuts
        cuts.cut("uv_env_max_age", "unused cached uv environments removed past the age", value=ENV_MAX_AGE_S,
                 kept=fresh, dropped=len(removed))
    return {"removed": removed, "bytes": freed, "in_use": kept_used, "fresh": fresh}


def prune_envs(now: float | None = None) -> dict:
    """prune_envs_at() on this machine's uv cache."""
    cache = cache_dir()
    return prune_envs_at(cache, now) if cache else {"skipped": "no uv cache"}
