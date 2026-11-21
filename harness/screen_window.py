"""A screen window: the interactive server's pinned models released for a screen that needs more than the free share, then restored (#2045)."""
from __future__ import annotations

import contextlib
import sys
import time

from harness import cuts, gateway_switch, interactive, memory, node_state, router

DRAIN_S = 120.0
IDLE_S = 1800.0


class Refused(RuntimeError):
    """The window did not open, or its pinned set was not confirmed back after it."""


def quiet_s(now: float | None = None, conn=None) -> float:
    """Seconds since the last interactive request on a lane pinned here ended: inf when none ran, 0 when unread. #2087."""
    from harness import runs
    now = time.time() if now is None else now
    try:
        with runs.store(conn) as c:
            last = interactive.last_request(c, now=now)
    except Exception as exc:  # noqa: BLE001 - an unread history never releases the pinned set
        print(f"window: the interactive requests could not be read ({exc}); the pinned set stays", file=sys.stderr)
        return 0.0
    return float("inf") if last is None else max(now - last, 0.0)


def wanted(need_gb: float | None, now: float | None = None) -> bool:
    """Whether a refused load of `need_gb` fits once the pinned set is released: always when only the pins hold it back, else when the set sat idle IDLE_S. #2087."""
    if not isinstance(need_gb, (int, float)) or need_gb <= 0:
        return False
    if memory.held_back(need_gb):
        return need_gb <= memory.standing_gb() + memory.pinned_gb() + 1e-9
    room = memory.room_gb()
    if need_gb <= room + 1e-9 or need_gb > room + memory.pinned_gb() + 1e-9:
        return False
    quiet = quiet_s(now)
    if quiet < IDLE_S:
        cuts.cut("sweep_window_idle", f"a {need_gb:.1f} GiB load: the last interactive request ended {quiet:.0f} s ago",
                 value=IDLE_S, kept=0, dropped=1)
        return False
    return True


def _status(plan: dict, get=None) -> tuple[str, dict | None]:
    """(server base, stem -> status), statuses None when the interactive server does not answer."""
    from harness import serving
    base = serving.bare(str(plan.get("url") or interactive.url()))
    return base, router.statuses(interactive._ask(base, get), base=base)


def _poster(base: str, post=None):
    secret = interactive.key()
    return post or (lambda p, b: router._post(p, b, base, **({"key": secret} if secret else {})))


def restore(plan: dict, get=None, post=None, sleep=time.sleep, clock=time.monotonic, released=()) -> list[str]:
    """Load the pinned set back and wait for it; the stems not loaded once WARM_WAIT_S is spent, a `released` one counting only once loaded after the router showed it gone. #2093."""
    stems = sorted({e["stem"] for e in (plan.get("lanes") or {}).values()})
    end, asked, released = clock() + interactive.WARM_WAIT_S, set(), set(released)
    while True:
        base, got = _status(plan, get)
        missing = [s for s in stems if (got or {}).get(s) != "loaded" or (s in released and s not in asked)]
        if not missing:
            return []
        want = [s for s in missing if got is not None and got.get(s) not in router.RESIDENT and s not in asked]
        if want:
            asked.update(interactive.load(want, base, _poster(base, post)))
        if clock() >= end:
            return missing
        sleep(interactive.WARM_POLL_S)


def _resident(plan: dict, stems, get=None, sleep=time.sleep, clock=time.monotonic) -> list[str]:
    """Wait up to DRAIN_S for the router to show each of `stems` gone, since an unload answers before it lands. #2093."""
    end = clock() + DRAIN_S
    while True:
        _, got = _status(plan, get)
        held = [s for s in stems if got is None or got.get(s) in router.RESIDENT]
        if not held or clock() >= end:
            return held
        sleep(interactive.WARM_POLL_S)


def _unrestored(missing: list[str], why: str, say) -> None:
    from harness import monitor
    text = f"{', '.join(missing)} did not load back on the interactive server after {why}"
    say(f"   WARN window: NOT restored: {text}")
    try:
        monitor.alert("service", {"MONIT_SERVICE": "interactive", "MONIT_DESCRIPTION": text[:400]})
    except Exception as exc:  # noqa: BLE001 - an alert that fails never hides the WARN
        say(f"   WARN window: the alert could not be sent: {exc}")


@contextlib.contextmanager
def opened(hold_s: float | None, why: str, *, keep=(), get=None, post=None, sleep=time.sleep, clock=time.monotonic,
           say=print):
    """Send interactive work to a node or the cloud, release the pinned set but `keep` for at most `hold_s`, then put it back."""
    if not hold_s:
        raise Refused("no engine bounds the screen, so the window could not be given an end")
    plan = interactive.read()
    stems = sorted({e["stem"] for e in (plan.get("lanes") or {}).values()})
    gone = [s for s in stems if s not in set(keep)]
    base, got = _status(plan, get)
    if not gone or not base:
        raise Refused("nothing is pinned here to release")
    if got is None or any(got.get(s) != "loaded" for s in stems):
        raise Refused(f"the pinned set is not all loaded now ({got}), so its restore could not be confirmed")
    interactive.keep_in_window([s for s in stems if s not in gone])
    gateway_switch.start_drain(time.time() + DRAIN_S + float(hold_s) + interactive.WARM_WAIT_S, node=interactive.WINDOW)
    missing: list[str] = []
    released: list[str] = []
    try:
        ask = interactive._ask(base, get) or (lambda path: router._get(path, base))
        start, busy = clock(), node_state._busy(ask, gone)
        while busy != 0 and clock() - start < DRAIN_S:
            sleep(interactive.WARM_POLL_S)
            busy = node_state._busy(ask, gone)
        if busy != 0:
            cuts.cut("screen_window_drain", f"{why}: interactive requests still in flight", kept=0, dropped=1)
            raise Refused(f"the interactive server still had {'unknown' if busy is None else busy} request(s) "
                          f"in flight after {DRAIN_S:g} s")
        unloaded = router.release(gone, why, get=interactive._ask(base, get), post=_poster(base, post), keep=set(),
                                  say=say, base=base, proven_idle=True)
        released = unloaded
        kept = _resident(plan, gone, get, sleep, clock)
        if kept:
            raise Refused(f"{', '.join(kept)} stayed resident on the interactive server")
        say(f"   window: released {', '.join(gone)} for at most {float(hold_s):.0f} s; interactive work goes to "
            f"a node or the cloud")
        yield gone
    finally:
        missing = restore(plan, get, post, sleep, clock, released=released)
        gateway_switch.stop_drain(node=interactive.WINDOW)
        interactive.keep_in_window(None)
        if missing:
            _unrestored(missing, why, say)
        else:
            say(f"   window: restored {', '.join(gone)}")
    if missing:
        raise Refused(f"{', '.join(missing)} did not load back in {interactive.WARM_WAIT_S:g} s")


@contextlib.contextmanager
def idle_release(hold_s: float | None, why: str, keep=(), *, now: float | None = None, say=print, **kw):
    """A sweep step's window: the pinned set but `keep` released when no interactive request ran in IDLE_S, else nothing released. #2087."""
    plan = interactive.read()
    gone = {e["stem"] for e in (plan.get("lanes") or {}).values()} - set(keep)
    if not hold_s or hold_s <= 0 or not gone or not interactive.reserved_bytes():
        yield []
        return
    quiet = quiet_s(now)
    if quiet < IDLE_S:
        cuts.cut("sweep_window_idle", f"{why}: the last interactive request ended {quiet:.0f} s ago", value=IDLE_S,
                 kept=0, dropped=1)
        say(f"   window: the last interactive request ended {quiet:.0f} s ago, under {IDLE_S:g} s; the pinned set stays")
        yield []
        return
    with contextlib.ExitStack() as stack:
        try:
            got = stack.enter_context(opened(hold_s, why, keep=keep, say=say, **kw))
        except Refused as exc:
            say(f"   window: not opened: {exc}")
            got = []
        yield got
