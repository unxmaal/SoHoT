"""uv's cache pruned by the disk sweep, never forced, skipped while another uv process holds its lock (#2049)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DIR_TIMEOUT_S = 30.0

PRUNE_TIMEOUT_S = 900.0

#: What uv prints first when another uv process holds the cache: it would wait for it, so the prune is skipped.
IN_USE = "Cache is currently in-use"
HELD = "another uv process holds the cache lock (any running `uv run`, this one's parent included); never forced"
_UNITS = {u: 1024 ** i for i, u in enumerate(("B", "KiB", "MiB", "GiB", "TiB"))}
_REMOVED = re.compile(r"\(([\d.]+)\s*(B|KiB|MiB|GiB|TiB)\)")


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


def removed_bytes(text: str) -> int:
    """The size in uv's `Removed N files (SIZE)` line; 0 when it removed nothing."""
    m = _REMOVED.search(text)
    return round(float(m.group(1)) * _UNITS[m.group(2)]) if m else 0


def prune_at(cache: Path, popen=None) -> dict:
    """`uv cache prune` on `cache`, never --force: {"bytes", "free"} or {"skipped": why}. Never raises."""
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
    try:
        rest, _ = proc.communicate(timeout=PRUNE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return {"skipped": f"uv cache prune ran past {PRUNE_TIMEOUT_S:.0f} s"}
    text = first + (rest or "")
    if proc.returncode != 0:
        return {"skipped": f"uv cache prune exited {proc.returncode}: {text.strip().splitlines()[-1:]}"}
    return {"bytes": removed_bytes(text), "free": shutil.disk_usage(cache).free}


def prune(popen=None) -> dict:
    """prune_at() on this machine's uv cache; OSError when uv cannot say where that is."""
    cache = cache_dir()
    return prune_at(cache, popen) if cache else {"skipped": "no uv cache to prune"}
