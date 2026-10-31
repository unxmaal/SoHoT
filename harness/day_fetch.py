"""`soh fetch --day`: download what the next night can screen, by day, beside no sweep and under a rate cap. #1084."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

#: Off until the owner turns it on: a value given once to launchd.sh install is kept beside the store.
ENABLE = "LH_DAY_FETCH"
#: Local hours the day fetch never runs in: the night sweep's, from the first to the second.
NIGHT_START_H, NIGHT_END_H = 20, 8
#: Local hours its download rate is capped in, from the first to the second.
CAP_START_H, CAP_END_H = 9, 16
#: The average download rate, MB/s, it holds inside those hours.
CAP_MB_S = 5.0
#: GiB one day fetch may download, as scripts/serve-fetch.sh passes it.
SITE_BUDGET = "scripts/serve-fetch.sh:DAY_FETCH_GIB"


def enabled(environ=None) -> bool:
    return (os.environ if environ is None else environ).get(ENABLE, "").strip() == "1"


def within(hour: float, start: float, end: float) -> bool:
    """`hour` falls in [start, end), a span that may wrap past midnight."""
    return start <= hour < end if start < end else hour >= start or hour < end


def _hour(now: float) -> float:
    t = time.localtime(now)
    return t.tm_hour + t.tm_min / 60


def night(now: float) -> bool:
    return within(_hour(now), NIGHT_START_H, NIGHT_END_H)


def capped(now: float) -> bool:
    return within(_hour(now), CAP_START_H, CAP_END_H)


def next_at(now: float, hour: float) -> float:
    """The next local time at `hour` after `now`."""
    at = datetime.fromtimestamp(now).replace(hour=int(hour), minute=int(hour % 1 * 60), second=0, microsecond=0)
    if at.timestamp() <= now:
        at += timedelta(days=1)
    return at.timestamp()


def busy(root=None, running=None) -> str:
    """What a sweep or eval is running now, or ''."""
    from harness import paths, sweep_guard
    got = (running or sweep_guard.running)(root or paths.home())
    return ", ".join(f"{r['what']} (pid {r['pid']})" for r in got)


def why_not_now(now: float, environ=None, running=None) -> str:
    """Why a day fetch starts nothing now, or ''."""
    if not enabled(environ):
        return f"the day fetch is off; {ENABLE}=1 at install turns it on"
    if night(now):
        return f"{NIGHT_START_H:02d}:00 to {NIGHT_END_H:02d}:00 belongs to the night sweep"
    got = busy(running=running)
    if got:
        return f"waits for what is running: {got}"
    return ""


def room(conn, backlog: int) -> tuple[int, str]:
    """(downloads to start, why): the screens a night's ceiling fits, less what already waits on disk."""
    from harness import ceiling, power
    per = ceiling.screen_s(conn)
    fits = ceiling.screen_capacity(conn)
    why = (f"a night's ceiling screens {fits} at about {power._hm(per)} each; "
           f"{backlog} already wait on disk")
    return max(0, fits - backlog), why


def budget_gib() -> float:
    from harness import knobs
    return float(knobs.KNOBS["day_fetch_budget"].default())


def child_argv(limit: int, budget: float, until: float) -> list[str]:
    return [sys.executable, "-m", "harness.cli", "fetch", "--run", "--limit", str(limit),
            "--budget-gib", f"{budget:g}", "--hold-router", "--until", f"{until:.0f}",
            "--limit-knob", "screen_fraction", "--budget-knob", "day_fetch_budget"]


def terminated(signum, _frame):
    """SIGTERM as an exit that runs the finally blocks."""
    raise SystemExit(128 + signum)


def _release(proc) -> None:
    """A child left stopped would hold its download forever: continue it, then end it."""
    import signal
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        proc.kill()
        return
    for sig in (signal.SIGCONT, signal.SIGTERM):
        try:
            os.kill(proc.pid, sig)
        except OSError:
            return
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def clear(strays=None, kill=None) -> list[str]:
    """Continue and end what a dead controller left: a stopped download, a spinning nettop. #1092."""
    from harness import throttle
    return throttle.reap(throttle.strays() if strays is None else strays, kill=kill)


def run(a, *, clock=time.time, popen=subprocess.Popen, counter=None, hold=None, backlog=None, store=None,
         running=None, environ=None) -> dict:
    """One day fetch: refuse, or start the fetch as a child and hold its rate under the cap in the capped hours."""
    from harness import throttle
    now = clock()
    why = why_not_now(now, environ, running)
    if why:
        return {"started": False, "why": why}
    if store is None:
        from harness import memory_store as ms
        store = ms.connect()
    try:
        if backlog is None:
            from harness.commands import screen as screen_cmd
            backlog = len(screen_cmd.screenable_backlog("", room=lambda r: True))
        limit, sized = room(store, backlog)
    finally:
        store.close()
    if limit <= 0:
        return {"started": False, "why": f"the buffer is full: {sized}"}
    count = counter or throttle.counter
    can_hold = counter is not None or throttle.available()
    night_at = next_at(now, NIGHT_START_H)
    until = night_at
    if not can_hold:
        if capped(now):
            return {"started": False, "why": "no per-process byte counter here, so the capped hours start no fetch"}
        until = min(until, next_at(now, CAP_START_H))
    budget = float(getattr(a, "budget_gib", None) or budget_gib())
    proc = popen(child_argv(limit, budget, until))
    read = count(proc.pid) if can_hold else None

    def stop() -> str:
        if clock() >= until:
            return "its window closed"
        return "a sweep or eval started" if busy(running=running) else ""

    try:
        got = (hold or throttle.hold)(proc, float(CAP_MB_S) * throttle.MB, read.poll if read else (lambda _w: 0),
                                      capped=lambda: read is not None and capped(clock()), stop=stop)
    finally:
        if read is not None and hasattr(read, "close"):
            read.close()
        _release(proc)
    return {"started": True, "why": sized, "limit": limit, "budget_gib": budget, "rc": proc.returncode, **got}
