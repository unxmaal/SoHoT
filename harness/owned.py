"""Child servers a process starts in their own session: recorded per owner, stopped on the owner's TERM or INT, reaped once the owner is gone. #1759."""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from harness.proc_identity import identity, same, started

TERM_GRACE_S = 10.0

_SIGNALS = ("SIGTERM", "SIGINT")

_children: dict[int, tuple[subprocess.Popen, dict]] = {}
_previous: dict[int, object] = {}
_pending: list[int] = []
_starting = False
_lock = threading.RLock()


def root() -> Path:
    from harness import paths
    return paths.home() / "owned"


def _file(owner: dict) -> Path:
    return root() / f"{owner['pid']}-{owner['started'] or 'unknown'}.json"


def _write() -> None:
    owner = identity(os.getpid())
    path = _file(owner)
    if not _children:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"owner": owner, "argv": sys.argv[:4],
                               "children": [rec for _, rec in _children.values()]}), encoding="utf-8")
    os.replace(tmp, path)


def _guard() -> None:
    """Route this process's TERM and INT through _on_signal, keeping what was there to call after; main thread only."""
    if threading.current_thread() is not threading.main_thread():
        return
    for name in _SIGNALS:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        cur = signal.getsignal(sig)
        if cur is _on_signal or cur is None or cur == signal.SIG_IGN:
            continue
        _previous[sig] = cur
        signal.signal(sig, _on_signal)


def _unguard() -> None:
    if threading.current_thread() is not threading.main_thread():
        return
    for sig, prev in list(_previous.items()):
        if signal.getsignal(sig) is _on_signal:
            signal.signal(sig, prev)
        _previous.pop(sig, None)


def _on_signal(signum, frame) -> None:
    if _starting:
        _pending.append(signum)
        return
    prev = _previous.get(signum, signal.SIG_DFL)
    if _children:
        print(f"{signal.Signals(signum).name}: stopping {len(_children)} server(s) this process started",
              file=sys.stderr, flush=True)
    stop_all()
    _unguard()
    if callable(prev):
        prev(signum, frame)
        return
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _signal(proc: subprocess.Popen, hard: bool) -> None:
    """The child's whole session where the OS has process groups, the child alone where it does not."""
    with contextlib.suppress(ProcessLookupError):
        if hasattr(os, "killpg") and hasattr(signal, "SIGKILL"):
            os.killpg(proc.pid, signal.SIGKILL if hard else signal.SIGTERM)
        elif hard:
            proc.kill()
        else:
            proc.terminate()


def start(cmd: list[str], **popen) -> subprocess.Popen:
    """Start cmd in its own session as this process's child: recorded, stopped on this process's TERM or INT."""
    global _starting
    for line in reap():
        print(line, file=sys.stderr, flush=True)
    _guard()
    if sys.platform == "win32":
        popen.setdefault("creationflags", subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        popen["start_new_session"] = True
    with _lock:
        _starting = threading.current_thread() is threading.main_thread()
        try:
            proc = subprocess.Popen(cmd, **popen)
            pgid = None if sys.platform == "win32" else proc.pid
            _children[proc.pid] = (proc, {"pid": proc.pid, "pgid": pgid, "started": started(proc.pid),
                                          "cmd": " ".join(str(c) for c in cmd)[:300]})
            _write()
        finally:
            _starting = False
            held, _pending[:] = list(_pending), []
            for sig in held:
                _on_signal(sig, None)
    return proc


def _forget(pid: int) -> None:
    with _lock:
        _children.pop(pid, None)
        _write()
        if not _children:
            _unguard()


def stop(proc: subprocess.Popen, grace: float = TERM_GRACE_S) -> None:
    """TERM the child's group, KILL it after grace, and drop its record."""
    try:
        if proc.poll() is None:
            _signal(proc, hard=False)
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                _signal(proc, hard=True)
                proc.wait()
    finally:
        _forget(proc.pid)


def stop_all(grace: float = TERM_GRACE_S) -> None:
    """Stop every child this process started, all within one grace."""
    with _lock:
        procs = [p for p, _ in _children.values()]
        for p in procs:
            if p.poll() is None:
                _signal(p, hard=False)
        deadline = time.monotonic() + grace
        for p in procs:
            try:
                p.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                _signal(p, hard=True)
                p.wait()
        for p in procs:
            _forget(p.pid)


def _stop_group(rec: dict, grace: float, sleep=time.sleep) -> str:
    """TERM a recorded child's group, KILL it if the child outlives grace: "term" or "kill"."""
    if sys.platform == "win32":
        return "unsupported"
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(int(rec["pgid"]), signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if same(rec) is not True:
            return "term"
        sleep(0.1)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(int(rec["pgid"]), signal.SIGKILL)
    return "kill"


def reap(act: bool = True, grace: float = TERM_GRACE_S) -> list[str]:
    """Stop the recorded children of owners that are gone, never a process that only reuses a recorded pid; a line per child."""
    lines, files = [], []
    with contextlib.suppress(OSError):
        files = sorted(root().glob("*.json"))
    for f in files:
        try:
            got = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        owner = got.get("owner") or {}
        if same(owner) is not False:
            continue
        unsure = False
        for c in got.get("children") or []:
            who = f"pid {c.get('pid')} ({str(c.get('cmd', ''))[:80]}), owner pid {owner.get('pid')} gone"
            alive = same(c)
            if alive is None:
                unsure = True
                lines.append(f"cannot tell whether {who} still runs; left alone")
            elif alive and act:
                lines.append(f"stopped {who}: {_stop_group(c, grace)}")
            elif alive:
                lines.append(f"would stop {who}")
        if act and not unsure:
            f.unlink(missing_ok=True)
    return lines
