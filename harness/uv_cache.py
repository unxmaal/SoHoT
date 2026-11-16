"""uv's cache pruned by the disk sweep, never forced, skipped while another uv process holds its lock (#2049)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

DIR_TIMEOUT_S = 30.0

PRUNE_TIMEOUT_S = 900.0

#: What uv prints first when another uv process holds the cache: it would wait for it, so the prune is skipped.
IN_USE = "Cache is currently in-use"
HELD = "another uv process holds the cache lock (any running `uv run`, this one's parent included); never forced"
_UNITS = {u: 1024 ** i for i, u in enumerate(("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"))}
_REMOVED = re.compile(r"^Removed \d+ (?:files?|director(?:y|ies))(?: \(([\d.]+)\s*([KMGTPE]?i?B)\))?\s*$", re.M)
_NOTHING = re.compile(r"^No unused entries found\s*$", re.M)


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
