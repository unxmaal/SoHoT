"""Remove the temp files a dead writer left beside its target, so the writer's next write is the repair (#1900)."""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

# Stdlib only: harness/sweep_guard.py loads this as a file when launchd.sh runs it with python3 -I.
try:
    from harness import proc_identity
except ImportError:  # loaded as a file: proc_identity is the stdlib-only module beside it
    import importlib.util
    _spec = importlib.util.spec_from_file_location("proc_identity", Path(__file__).with_name("proc_identity.py"))
    proc_identity = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(proc_identity)

FLOOR_S = 60.0
_FIELDS = {"{pid}": r"(?P<pid>[1-9]\d{0,8})", "{thread}": r"\d+", "{hex}": r"[0-9a-f]+"}

clock = time.time


def _pattern(name: str, form: str) -> re.Pattern:
    """form as a pattern over sibling names; a field it does not know, or no {pid} to prove a writer gone, is refused."""
    out = []
    for part in re.split(r"(\{\w*\})", form):
        if part == "{name}":
            out.append(re.escape(name))
        elif part.startswith("{") and part not in _FIELDS:
            raise ValueError(f"temp form {form!r}: {part} is not one of {{name}} {' '.join(_FIELDS)}")
        else:
            out.append(_FIELDS.get(part) or re.escape(part))
    if "{pid}" not in form:
        raise ValueError(f"temp form {form!r} names no {{pid}}, so nothing could prove its writer gone")
    return re.compile("".join(out) + r"\Z")


def sweep(target, form: str) -> list[Path]:
    """Remove each sibling of target named by form whose writer pid is gone and that is FLOOR_S old; the paths removed."""
    target = Path(target)
    pattern, now, gone = _pattern(target.name, form), clock(), []
    try:
        entries = list(os.scandir(target.parent))
    except OSError:
        return gone
    for entry in entries:
        got = pattern.match(entry.name)
        if not got:
            continue
        try:
            if now - entry.stat(follow_symlinks=False).st_mtime < FLOOR_S:
                continue
        except OSError:
            continue
        if proc_identity.same({"pid": int(got["pid"])}) is not False:
            continue  # alive, or cannot say: its writer may still replace it
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)
        except OSError:
            continue
        gone.append(Path(entry.path))
    return gone


def temp(target, form: str) -> Path:
    """The temp path this process and thread write target through, named by form, once a dead writer's are swept."""
    target = Path(target)
    sweep(target, form)
    return target.with_name(form.format(name=target.name, pid=os.getpid(), thread=threading.get_ident(),
                                        hex=uuid.uuid4().hex[:8]))
