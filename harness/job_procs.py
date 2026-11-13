"""A queued job's process: its pid record and flag files beside it, and its process group's life and stop. #628, #1902."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from harness import job_state as js

def _pids() -> Path:
    from harness import workqueue as wq
    d = wq.root() / "running"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pid_file(job_id) -> Path:
    from harness import workqueue as wq
    return _pids() / f"{wq.label(job_id)}.pid"


def _cancel_flag(job_id) -> Path:
    from harness import workqueue as wq
    return _pids() / f"{wq.label(job_id)}.cancel"


def _item_flag(job_id) -> Path:
    from harness import workqueue as wq
    return _pids() / f"{wq.label(job_id)}.item"


def _deploy_flag(job_id) -> Path:
    from harness import workqueue as wq
    return _pids() / f"{wq.label(job_id)}.deploy"


def _stop_flag(job_id) -> Path:
    from harness import workqueue as wq
    return _pids() / f"{wq.label(job_id)}.stopped"


def _flag_files(job_id) -> dict:
    """job_state flag name -> its file beside the job's pid file."""
    return {js.CANCEL_FLAG: _cancel_flag(job_id), js.STOP_FLAG: _stop_flag(job_id),
            js.ITEM_FLAG: _item_flag(job_id), js.DEPLOY_FLAG: _deploy_flag(job_id)}


def _flags(job_id) -> frozenset:
    """The flags set for a job, read once to choose its next move."""
    return frozenset(k for k, f in _flag_files(job_id).items() if f.exists())


def _clear_flags(job_id) -> None:
    from harness import executors
    for f in (*_flag_files(job_id).values(), executors.exit_file(_pid_file(job_id))):
        f.unlink(missing_ok=True)


def _pid_of(job_id) -> int | None:
    from harness import executors
    try:
        pid, started = executors.pid_record(_pid_file(job_id))
    except (OSError, ValueError):
        return None
    return pid if alive(pid) and _leads(pid, started) else None


def _leads(pid: int, started: str = "") -> bool:
    """Whether pid is still the job's started process: its own group's leader, started when its pid file says; a reused pid is not. #1728, #1820."""
    from harness import proc_identity
    return proc_identity.same({"pid": int(pid), "pgid": int(pid), "started": started}) is not False


def spawn_group(argv, cwd, stdout, env) -> subprocess.Popen:
    """Start argv as the leader of a new process group, stderr into stdout. #628."""
    if sys.platform == "win32":
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        group = {"start_new_session": True}
    return subprocess.Popen(argv, cwd=cwd or None, stdout=stdout,
                            stderr=subprocess.STDOUT, env=env, **group)


def alive(pid: int) -> bool:
    """Whether a process with this pid exists (a zombie counts until reaped)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x101000, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_alive(pid: int, proc=None) -> bool:
    """Whether a member of pid's group can still take a signal; reaps proc, the caller's own leader, first. #677."""
    if proc is not None:
        proc.poll()
    if sys.platform == "win32":
        return alive(pid)
    try:
        os.killpg(int(pid), 0)
    except (ProcessLookupError, PermissionError):  # EPERM on macOS: every member is a zombie or inside exit
        return sys.platform == "darwin" and _exiting_member(int(pid))
    if sys.platform.startswith("linux"):
        return _live_member(int(pid))
    return True


_KINFO_SIZE, _KINFO_P_STAT, _SZOMB = 648, 36, 5


def _pgrp_states(pgid: int):
    """The p_stat of each process in pgid, from macOS sysctl KERN_PROC_PGRP; None if unreadable. #1237."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    mib = (ctypes.c_int * 4)(1, 14, 2, int(pgid))  # CTL_KERN, KERN_PROC, KERN_PROC_PGRP
    size = ctypes.c_size_t(0)
    if libc.sysctl(mib, 4, None, ctypes.byref(size), None, 0):
        return None
    buf = ctypes.create_string_buffer(size.value + _KINFO_SIZE * 8)
    size = ctypes.c_size_t(len(buf))
    if libc.sysctl(mib, 4, buf, ctypes.byref(size), None, 0) or size.value % _KINFO_SIZE:
        return None
    return [buf.raw[off + _KINFO_P_STAT] for off in range(0, size.value, _KINFO_SIZE)]


def _exiting_member(pgid: int, read=_pgrp_states) -> bool:
    """macOS will not signal a member inside exit, which keeps its files until it is a zombie; unreadable counts. #1237."""
    states = read(pgid)
    return states is None or any(state != _SZOMB for state in states)


def _live_member(pgid: int, proc_root="/proc") -> bool:
    """Linux answers killpg for a group of zombies, so read each member's state; unreadable counts as live. #677."""
    try:
        names = os.listdir(proc_root)
    except OSError:
        return True
    seen = False
    for name in names:
        if not name.isdigit():
            continue
        try:
            stat = Path(proc_root, name, "stat").read_text(encoding="utf-8")
        except OSError:
            continue
        state, _, group = (stat.rpartition(")")[2].split() + ["", "", ""])[:3]
        if group == str(pgid):
            seen = True
            if state not in ("Z", "X"):
                return True
    return not seen


def stop_group(pid: int, grace: float | None = None, sleep=time.sleep, proc=None) -> str:
    """Signal the process group led by pid, wait up to `grace`, then kill it: "term", "kill" or "gone". #628, #677."""
    from harness import workqueue as wq
    grace = wq.CANCEL_GRACE_S if grace is None else grace
    if not _group_alive(pid, proc):
        return "gone"
    if sys.platform == "win32":
        # The tree is walked from a live leader, and a console child has no SIGTERM to catch.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(int(pid))], capture_output=True)
        deadline = time.monotonic() + grace
        while _group_alive(pid, proc) and time.monotonic() < deadline:
            sleep(0.1)
        return "kill"
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        if not _group_alive(pid, proc):
            return "gone"
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _group_alive(pid, proc):
            return "term"
        sleep(0.1)
    try:
        os.killpg(int(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return "term"
    return "kill"


def _tree(pid: int) -> list[tuple[int, str]]:
    """(pid, command) of pid and every process under it, in any session, from ps; [] where there is none to ask. #1675."""
    from harness import sweep_guard
    if sys.platform == "win32":
        return []
    try:
        got = subprocess.run(["ps", "-ww", "-axo", "pid=,ppid=,command="], capture_output=True, text=True,
                             timeout=sweep_guard.PS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"{time.strftime('%H:%M:%S')} could not list the processes of pid {pid}: {exc}", flush=True)
        return []
    rows = [r for r in (ln.split(None, 2) for ln in got.stdout.splitlines()) if len(r) >= 2 and r[0].isdigit()]
    kids: dict[str, list] = {}
    for r in rows:
        kids.setdefault(r[1], []).append(r)
    found, seen, todo = [], set(), [r for r in rows if r[0] == str(pid)]
    while todo:
        r = todo.pop(0)
        if r[0] in seen:
            continue
        seen.add(r[0])
        found.append((int(r[0]), r[2] if len(r) == 3 else ""))
        todo += kids.get(r[0], [])
    return found


def _evals_in(pid: int) -> list[int]:
    """Pids of the evals.run processes under pid: measure starts each in a session of its own, so not its group. #1672, #1675."""
    from harness import sweep_guard
    return [p for p, command in _tree(pid) if sweep_guard.EVAL.search(command)]


def item_ended(environ=None) -> bool:
    """Mark that this queued job stopped at its item's end with cases left, so the worker queues its next item. #1618."""
    from harness import workqueue as wq
    key = wq._key((environ if environ is not None else os.environ).get(wq.JOB_ENV, ""))
    if key is None:
        return False
    _item_flag(key).write_text(time.strftime(wq._STAMP), encoding="utf-8")
    return True


def item_s(environ=None) -> float | None:
    """The seconds of this process's queue item, when the worker runs its job in items; None otherwise. #1618."""
    from harness import workqueue as wq
    try:
        got = float((environ if environ is not None else os.environ).get(wq.ITEM_ENV, ""))
    except ValueError:
        return None
    return got if got > 0 else None


def _bin(venv: Path) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin")


def job_venv(cwd, environ) -> dict:
    """environ with VIRTUAL_ENV and its PATH entry moved to the .venv of the checkout cwd is in, or dropped. #1655."""
    env = dict(environ)
    was = env.pop("VIRTUAL_ENV", "")
    if not was:
        return env
    here = Path(cwd).resolve()
    root = next((p for p in (here, *here.parents) if (p / "pyproject.toml").is_file()), None)
    venv = root / ".venv" if root is not None and (root / ".venv").is_dir() else None
    if venv is not None:
        env["VIRTUAL_ENV"] = str(venv)
    if "PATH" in env:
        old = os.path.normcase(str(_bin(Path(was))))
        new = str(_bin(venv)) if venv is not None else ""
        moved = (new if os.path.normcase(p) == old else p for p in env["PATH"].split(os.pathsep))
        env["PATH"] = os.pathsep.join(p for p in moved if p)
    return env
