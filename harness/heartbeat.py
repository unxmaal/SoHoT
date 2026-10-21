"""What the discovery loop is doing while it runs, and whether it is still alive. #251."""
from __future__ import annotations

import contextlib
import json
import os
import plistlib
import re
import time
from pathlib import Path

RUNNING = "running"
FINISHED = "finished"
#: No progress for this long reads as stalled when the step declared no deadline of its own. #705.
STALL_S = 3 * 3600
#: How late a sweep may start past the installed discover schedule's longest gap. #625, #705.
SWEEP_SLACK_S = 3600

clock = time.time


def path() -> Path:
    from harness import paths
    return paths.home() / "loop-heartbeat.json"


def ago(seconds: float) -> str:
    """Return a short human-readable duration for a number of seconds."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        hours = seconds // 3600
        minutes = seconds % 3600 // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days = seconds // 86400
    hours = seconds % 86400 // 3600
    return f"{days}d {hours}h" if hours else f"{days}d"


def alive(pid: int) -> bool:
    """Does a process with this pid exist here; unknown counts as alive."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _write(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, p)


def read() -> dict | None:
    try:
        got = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _mine() -> dict | None:
    got = read()
    return got if got and got.get("pid") == os.getpid() else None


#: When a loop last handed stale too-big refusals back to inspect; kept across loops. #904.
REOPENED_TOO_BIG = "reopened_too_big"
#: When a loop last re-read every attachment's card under #949's rule; kept across loops.
REDERIVED_ATTACHMENTS = "rederived_attachments_949"
#: When a loop last requeued the refusals sized by the listing's sum, on code that sizes by variant. #947, #972.
REQUEUED_OLD_SIZING = "requeued_old_sizing_947"
#: When a loop last requeued the weights a parent's ranking retired. #954, #972.
REOPENED_UNRANKED = "reopened_unranked_954"
#: When a loop last rewrote every screen runtime decline's until by its cause. #950, #972.
REWROTE_RUNNER_GAPS = "rewrote_runner_gaps_950"
#: When a loop last requeued the refusals whose until this machine meets. #1055.
REOPENED_REVISITABLE = "reopened_revisitable_1055"
#: When a loop last moved past-screen reopens from inspect to the measure queue. #1060.
MOVED_PAST_SCREEN = "moved_past_screen_1060"
KEPT = (REOPENED_TOO_BIG, REDERIVED_ATTACHMENTS, REQUEUED_OLD_SIZING, REOPENED_UNRANKED, REWROTE_RUNNER_GAPS,
        REOPENED_REVISITABLE, MOVED_PAST_SCREEN)


def code_commit(repo: Path | None = None) -> str:
    """The commit the checkout this code was imported from has checked out, read from .git; '' when unreadable. #1000."""
    from harness import paths
    repo = paths.REPO if repo is None else Path(repo)
    try:
        git = repo / ".git"
        gitdir = git
        if git.is_file():
            gitdir = Path(git.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
            gitdir = gitdir if gitdir.is_absolute() else repo / gitdir
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head
        ref = head[4:].strip()
        common = gitdir
        if (gitdir / "commondir").is_file():
            common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
        for d in (gitdir, common):
            if (d / ref).is_file():
                return (d / ref).read_text(encoding="utf-8").strip()
        packed = (common / "packed-refs").read_text(encoding="utf-8").splitlines()
    except (OSError, IndexError, UnicodeDecodeError):
        return ""
    return next((line.split()[0] for line in packed if line.endswith(f" {ref}")), "")


def code_moved(data: dict | None, head: str = "", alive=alive) -> str:
    """How the commit a loop started on differs from the one it finished on, or from `head` while it runs; '' when not. #1000."""
    start = (data or {}).get("commit") or ""
    if not start:
        return ""
    if data.get("state") == FINISHED:
        end, how = data.get("finished_commit") or "", "finished on"
    elif alive(data.get("pid") or 0):
        end, how = head, "is still running under"
    else:
        return ""
    if not end or end == start:
        return ""
    return (f"the sweep started on {start[:8]} and {how} {end[:8]}: a deploy landed under it, "
            f"so it ran {start[:8]}'s code")


def start(lane: str = "", total: int = 0) -> dict:
    now = clock()
    kept = {k: v for k, v in (read() or {}).items() if k in KEPT}
    data = {**kept, "state": RUNNING, "pid": os.getpid(), "lane": lane, "tier": "",
            "candidate": "", "step": 0, "total": int(total), "item": 0, "items": 0,
            "started": now, "updated": now, "finished": None, "rc": None, "error": "",
            "commit": code_commit()}
    _write(data)
    return data


def beat(tier: str, step: int, total: int | None = None, candidate: str = "",
         item: int = 0, items: int = 0) -> None:
    """Record progress; a no-op unless this process started the heartbeat."""
    data = _mine()
    if data is None or data.get("state") != RUNNING:
        return
    data.update(tier=tier, step=int(step), candidate=candidate, item=int(item),
                items=int(items), updated=clock(), deadline_s=None, waiting="")
    if total is not None:
        data["total"] = int(total)
    _write(data)


def expect(deadline_s: float | None, waiting: str = "") -> None:
    """Record the current step's deadline, or what it is waiting behind; a no-op unless this process started it."""
    data = _mine()
    if data is None or data.get("state") != RUNNING:
        return
    data.update(deadline_s=float(deadline_s) if deadline_s else None, waiting=waiting, updated=clock())
    _write(data)


def waiting(message: str) -> None:
    """Record that this loop waits behind the machine lock, for as long as its holder declared."""
    from harness import exclusive
    expect(exclusive.holder().get("deadline_s"), waiting=message)


@contextlib.contextmanager
def held(kind: str, deadline_s: float | None = None, say=None):
    """Take the machine lock declaring `deadline_s`; while waiting, the loop reads the holder's deadline. #705."""
    from harness import exclusive

    def announce(message):
        if say:
            say(message)
        waiting(message)

    with exclusive.held(kind, announce=announce, deadline_s=deadline_s) as waited:
        expect(deadline_s)
        yield waited


def mark(key: str, at: float | None = None) -> None:
    """Record when this loop did `key`; a no-op unless this process started the heartbeat."""
    data = _mine()
    if data is None or data.get("state") != RUNNING:
        return
    data[key] = clock() if at is None else float(at)
    _write(data)


#: The sweep ceiling a finished loop left unused and why, or None. #1082.
CEILING_UNUSED = "ceiling_unused"


def note(key: str, value) -> None:
    """Record a JSON value under `key` on this loop's heartbeat; a no-op unless this process started it."""
    data = _mine()
    if data is None or data.get("state") != RUNNING:
        return
    data[key] = value
    _write(data)


def marked(key: str, data=None) -> float | None:
    """When a loop last did `key`, or None. #972."""
    data = read() if data is None else data
    got = (data or {}).get(key)
    return float(got) if got else None


def reopened_too_big(data=None) -> float | None:
    """When a loop last requeued the stale too-big refusals, or None. #904."""
    return marked(REOPENED_TOO_BIG, data)


def stall_after(data: dict) -> float:
    """Seconds without a beat before this loop reads as stalled: the step's own deadline when it set one."""
    return max(STALL_S, float(data.get("deadline_s") or 0))


def finish(rc: int | None = None, error: str = "") -> None:
    data = _mine()
    if data is None:
        return
    now = clock()
    data.update(state=FINISHED, rc=rc, error=error, finished=now, updated=now, finished_commit=code_commit())
    _write(data)


def status(data: dict | None, alive=alive) -> str:
    if not data:
        return ""
    if data.get("state") == FINISHED:
        return "finished"
    if not alive(data.get("pid") or 0):
        return "stalled"
    if clock() - float(data.get("updated") or 0) > stall_after(data):
        return "stalled"
    return "running"


def _where(d: dict) -> str:
    out = f"{d.get('tier') or 'starting'}, step {d.get('step', 0)} of {d.get('total', 0)}"
    if d.get("candidate"):
        out += f", {d['candidate']}"
        if d.get("items"):
            out += f" ({d.get('item', 0)} of {d['items']})"
    if d.get("waiting"):
        out += f", {d['waiting']}"
    return out


def summary(alive=alive) -> dict | None:
    """The heartbeat, its status and age, and one line saying so; None when no loop has run."""
    d = read()
    if d is None:
        return None
    st = status(d, alive=alive)
    now = clock()
    age = now - float(d.get("updated") or now)
    lane = f" ({d['lane']} lane)" if d.get("lane") else ""
    if st == "finished":
        rc = d.get("rc")
        how = f"rc {rc}" if rc is not None else f"error: {d.get('error', '')}"
        line = f"last discovery loop{lane} finished {ago(age)} ago, {how}"
    elif st == "stalled":
        gone = "" if alive(d.get("pid") or 0) else f", process {d.get('pid')} is gone"
        line = (f"discovery loop stalled{lane}: no progress for {ago(age)}{gone}; "
                f"last at {_where(d)}")
    else:
        line = (f"discovery loop running{lane}: {_where(d)}; started "
                f"{ago(now - float(d.get('started') or now))} ago, last progress "
                f"{ago(age)} ago")
    return {**d, "status": st, "age_s": age, "line": line}


def sweep_every_s(hours) -> int:
    """The longest gap in seconds between consecutive daily firings at these local hours."""
    got = sorted({int(h) % 24 for h in hours})
    if not got:
        return 24 * 3600
    gaps = [b - a for a, b in zip(got, got[1:])] + [got[0] + 24 - got[-1]]
    return max(gaps) * 3600


def discover_unit() -> Path:
    """Where scripts/launchd.sh installs the discover agent."""
    from harness import volume
    return volume.agent_unit(f"{volume.PREFIX}.discover")


def _hours(text: str) -> list[int]:
    return sorted(int(h) for h in text.split())


def _installed_hours() -> list[int]:
    try:
        cal = plistlib.loads(discover_unit().read_bytes()).get("StartCalendarInterval")
        cal = [cal] if isinstance(cal, dict) else list(cal or [])
        return sorted(int(c["Hour"]) for c in cal if isinstance(c, dict) and "Hour" in c)
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def _default_hours() -> list[int]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "launchd.sh"
    try:
        m = re.search(r'^DISCOVER_HOURS="\$\{DISCOVER_HOURS:-([^}]+)\}"',
                      script.read_text(encoding="utf-8"), re.M)
        return _hours(m.group(1)) if m else []
    except (OSError, ValueError):
        return []


def _env_hours() -> list[int]:
    try:
        return _hours(os.environ.get("DISCOVER_HOURS", ""))
    except ValueError:
        return []


def discover_hours() -> list[int]:
    """The installed discover agent's hours, else DISCOVER_HOURS, else scripts/launchd.sh's default."""
    return _installed_hours() or _env_hours() or _default_hours() or [21]


def overdue(data=None) -> str:
    """'' when the last discovery loop started within the schedule's longest gap plus SWEEP_SLACK_S; otherwise why."""
    if data is None:
        data = read()
    if data is None or "started" not in data:
        return "no discovery loop has run on this machine"
    every = sweep_every_s(discover_hours())
    age = clock() - float(data["started"])
    if age <= every + SWEEP_SLACK_S:
        return ""
    return f"last discovery loop started {ago(age)} ago; the schedule starts one every {ago(every)}"
