"""Who holds a queue pause flag: a dead holder's pause is lifted, an owner's never is. #1760."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from harness import proc_identity

#: The env var a script sets to its own pid, so a pause it takes is lifted once that pid is gone.
HOLDER_ENV = "LH_QUEUE_HOLDER"
_TAG = "holder "
_STAMP = "%Y-%m-%dT%H:%M:%S"
_BY = "by "
_DISK = "disk "
_SAYS = (("session", "CLAUDE_CODE_SESSION_ID"), ("agent", "AI_AGENT"), ("subagent", "CLAUDE_CODE_CHILD_SESSION"))
#: What a pause taken with no reason says in its place, so it reads as flagged. #2064.
NO_REASON = "no reason given"


def caller(environ=None) -> dict:
    """Who takes a pause: this process, its parent, its argv, and the agent session that ran it when one did. #2064."""
    env = environ if environ is not None else os.environ
    rec = {"pid": os.getpid(), "ppid": os.getppid(), "argv": [a[:200] for a in sys.argv[:12]]}
    rec.update({k: env[v] for k, v in _SAYS if env.get(v)})
    return rec


def text(why: str, holder: int | None, environ=None, disk: str | None = None) -> str:
    """A flag's body: when and why, the holder's identity or the disk it waits on, then who took it. #1760, #2064, #2066."""
    lines = [f"{time.strftime(_STAMP)} {why.strip() or NO_REASON}"]
    if holder is not None:
        lines.append(f"{_TAG}{json.dumps(proc_identity.identity(holder))}")
    if disk is not None:
        lines.append(f"{_DISK}{json.dumps({'path': disk, 'free_gib': free_gib(disk)})}")
    return "\n".join([*lines, f"{_BY}{json.dumps(caller(environ))}"])


def _line(body: str, tag: str) -> dict | None:
    for line in body.splitlines()[1:]:
        if line.startswith(tag):
            try:
                got = json.loads(line[len(tag):])
            except ValueError:
                return None
            return got if isinstance(got, dict) else None
    return None


def holder_of(body: str) -> dict | None:
    """The identity a flag body records, None for an owner's pause."""
    return _line(body, _TAG)


def disk_of(body: str) -> dict | None:
    """The volume a disk pause waits on, None for any other pause. #2066."""
    got = _line(body, _DISK)
    return got if got is not None and isinstance(got.get("path"), str) else None


def free_gib(path: str) -> float | None:
    try:
        return round(shutil.disk_usage(path).free / 1024 ** 3, 1)
    except OSError:
        return None


def free_said(path: str) -> str:
    free = free_gib(path)
    return f"{path} unreadable, so it stays paused" if free is None else f"{free} GiB free on {path}"


def resume_gib() -> int:
    """Free GiB at which a disk pause lifts itself: monit's pause floor plus the hysteresis knob. #2066."""
    from harness import monitor
    return monitor.DISK_PAUSE_GIB + monitor.DISK_RESUME_GIB


def _gone(body: str) -> str | None:
    """Why the pause in `body` no longer holds: its holder is gone, or the disk it waits on has room again."""
    rec = holder_of(body)
    if rec is not None and proc_identity.same(rec) is False:
        return f"its holder pid {rec.get('pid')} is gone"
    disk = disk_of(body)
    free = free_gib(disk["path"]) if disk is not None else None
    if free is not None and free >= resume_gib():
        from harness import cuts
        cuts.cut("harness/monitor.py:DISK_RESUME_GIB", f"disk pause lifted at {free} GiB free on {disk['path']}")
        return f"{disk['path']} has {free} GiB free, at least {resume_gib()} GiB"
    return None


def by_of(body: str) -> dict | None:
    """Who took the pause a flag body records, None for a flag written before #2064."""
    return _line(body, _BY)


def since(body: str) -> float | None:
    """When the pause was taken, from its stamp; None when the body has none."""
    stamp = (body.split(None, 1) or [""])[0]
    try:
        return time.mktime(time.strptime(stamp, _STAMP))
    except ValueError:
        return None


def reason(body: str) -> str:
    head = (body.splitlines() or [""])[0].split(None, 1)
    return head[1].strip() if len(head) > 1 and head[1].strip() else NO_REASON


def who(body: str) -> str:
    """The caller a flag names: its command, pid and agent session; an old flag says nobody recorded it."""
    by = by_of(body)
    if by is None:
        return "an unrecorded caller (no holder line)"
    argv = [str(a) for a in by.get("argv") or []]
    cmd = " ".join([Path(argv[0]).name, *argv[1:]]) if argv else "?"
    said = [f"`{cmd}` pid {by.get('pid')}"]
    if by.get("agent"):
        said.append(str(by["agent"]) + (" subagent" if by.get("subagent") else ""))
    if by.get("session"):
        said.append(f"session {str(by['session'])[:8]}")
    return ", ".join(said)


_DEPLOY_WHY = re.compile(r"^(?:deploy (\d+) of |held for a deploy)")


def deploy_hold(body: str) -> dict | None:
    """The deploy a pause belongs to and whether its process is still there, None for any other pause. #2141."""
    why = reason(body)
    got = _DEPLOY_WHY.match(why)
    if got is None:
        return None
    rec, by = holder_of(body), by_of(body) or {}
    if rec is not None:
        live = proc_identity.same(rec) is not False
        pid = rec.get("pid")
    else:
        pid = by.get("pid")
        began = proc_identity.began(int(pid)) if isinstance(pid, int) else None
        live = began is not None and began <= (since(body) or time.time()) + 2
    return {"id": int(got.group(1)) if got.group(1) else None, "pid": pid, "live": live}


def describe(body: str) -> str:
    stamp = (body.split(None, 1) or ["?"])[0]
    return f"since {stamp} by {who(body)}: {reason(body)}"


def from_env(environ=None) -> int | None:
    got = (environ if environ is not None else os.environ).get(HOLDER_ENV, "")
    return int(got) if got.isdigit() else None


def lift(flags: list[Path]) -> list[str]:
    """Remove each flag whose holder is gone or whose disk has room again; one that cannot be read ('cannot say') stays."""
    said = []
    for flag in flags:
        try:
            body = flag.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        gone = _gone(body)
        if gone is None:
            continue
        try:
            if flag.read_text(encoding="utf-8") != body:
                continue  # paused again since it was read
        except FileNotFoundError:
            continue
        flag.unlink(missing_ok=True)
        said.append(f"{flag.name} lifted: {gone} ({body.splitlines()[0]})")
    for line in said:
        print(f"{time.strftime('%H:%M:%S')} {line}", file=sys.stderr, flush=True)
    return said


def why_paused(flag: Path) -> str:
    """The gate's reason for a paused queue: an owner's pause, or the process whose end lifts it."""
    try:
        body = flag.read_text(encoding="utf-8")
    except FileNotFoundError:
        body = ""
    rec, disk = holder_of(body), disk_of(body)
    if disk is not None:
        return (f"paused {describe(body)}; {free_said(disk['path'])}, "
                f"lifts itself at {resume_gib()} GiB (soh jobs resume)")
    if rec is None:
        return f"paused {describe(body)} (soh jobs resume)"
    return f"held by pid {rec.get('pid')} ({body.splitlines()[0]}); lifted when it ends"


def release(held: Path, flag: Path) -> str:
    """Lift the deploy hold whose marker is held; an owner's pause, or one set since, stays. #1675."""
    if not held.exists():
        return "queue not held for a deploy; left as it was"
    mine = held.read_text(encoding="utf-8")
    held.unlink(missing_ok=True)
    if flag.exists() and flag.read_text(encoding="utf-8") == mine:
        flag.unlink(missing_ok=True)
        return "queue released after the deploy"
    return "queue left as it is: it was paused again during the deploy (soh jobs resume)"
