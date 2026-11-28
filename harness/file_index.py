"""Per-file results kept on disk by (path, mtime_ns, size), so a restart reads only the files that changed (#2191)."""
from __future__ import annotations

import os
import pickle
from pathlib import Path

from harness import atomic_file


def file_for(name: str) -> Path:
    from harness import paths
    return paths.home() / "cache" / "index" / f"{name}.pickle"


def read(name: str, version: int) -> dict:
    """The entries `write` kept under `name`, {} when there are none, they are unreadable or they are another version."""
    try:
        got = pickle.loads(file_for(name).read_bytes())
        return got[1] if got[0] == version and isinstance(got[1], dict) else {}
    except (OSError, ValueError, EOFError, pickle.UnpicklingError, IndexError, TypeError, AttributeError):
        return {}


def write(name: str, version: int, entries: dict) -> bool:
    """`entries` under `name`, replacing the file whole; False when the home cannot be written, which keeps nothing."""
    file = file_for(name)
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(pickle.dumps((version, entries), protocol=pickle.HIGHEST_PROTOCOL))
        atomic_file.replace(tmp, file)
    except OSError:
        return False
    return True
