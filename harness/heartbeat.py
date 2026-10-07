"""What the discovery loop is doing while it runs, and whether it is still alive. #251."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

RUNNING = "running"
FINISHED = "finished"
#: No progress for this long reads as stalled: above the longest single measure seen, below a day.
STALL_S = 3 * 3600

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


def start(lane: str = "", total: int = 0) -> dict:
    now = clock()
    data = {"state": RUNNING, "pid": os.getpid(), "lane": lane, "tier": "",
            "candidate": "", "step": 0, "total": int(total), "item": 0, "items": 0,
            "started": now, "updated": now, "finished": None, "rc": None, "error": ""}
    _write(data)
    return data


def beat(tier: str, step: int, total: int | None = None, candidate: str = "",
         item: int = 0, items: int = 0) -> None:
    """Record progress; a no-op unless this process started the heartbeat."""
    data = _mine()
    if data is None or data.get("state") != RUNNING:
        return
    data.update(tier=tier, step=int(step), candidate=candidate, item=int(item),
                items=int(items), updated=clock())
    if total is not None:
        data["total"] = int(total)
    _write(data)


def finish(rc: int | None = None, error: str = "") -> None:
    data = _mine()
    if data is None:
        return
    now = clock()
    data.update(state=FINISHED, rc=rc, error=error, finished=now, updated=now)
    _write(data)


def status(data: dict | None, alive=alive) -> str:
    if not data:
        return ""
    if data.get("state") == FINISHED:
        return "finished"
    if clock() - float(data.get("updated") or 0) > STALL_S or not alive(data.get("pid") or 0):
        return "stalled"
    return "running"


def _where(d: dict) -> str:
    out = f"{d.get('tier') or 'starting'}, step {d.get('step', 0)} of {d.get('total', 0)}"
    if d.get("candidate"):
        out += f", {d['candidate']}"
        if d.get("items"):
            out += f" ({d.get('item', 0)} of {d['items']})"
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
