"""A screen window: the interactive server's pinned models released for a screen that needs more than the free share, then restored (#2045)."""
from __future__ import annotations

import contextlib
import time

from harness import cuts, gateway_switch, interactive, memory, node_state, router

DRAIN_S = 120.0


class Refused(RuntimeError):
    """The window did not open, or its pinned set was not confirmed back after it."""


def wanted(need_gb: float | None) -> bool:
    """Whether a load of `need_gb` is kept out only by the pinned set, so a window would let it load."""
    if not isinstance(need_gb, (int, float)) or not memory.held_back(need_gb):
        return False
    return need_gb <= memory.standing_gb() + memory.pinned_gb() + 1e-9


def _status(plan: dict, get=None) -> tuple[str, dict | None]:
    """(server base, stem -> status), statuses None when the interactive server does not answer."""
    from harness import serving
    base = serving.bare(str(plan.get("url") or interactive.url()))
    return base, router.statuses(interactive._ask(base, get), base=base)


def _poster(base: str, post=None):
    secret = interactive.key()
    return post or (lambda p, b: router._post(p, b, base, **({"key": secret} if secret else {})))


def restore(plan: dict, get=None, post=None, sleep=time.sleep, clock=time.monotonic) -> list[str]:
    """Load the pinned set back and wait for it; the stems still not loaded once interactive.WARM_WAIT_S is spent."""
    stems = sorted({e["stem"] for e in (plan.get("lanes") or {}).values()})
    end, asked = clock() + interactive.WARM_WAIT_S, set()
    while True:
        base, got = _status(plan, get)
        missing = [s for s in stems if (got or {}).get(s) != "loaded"]
        if not missing:
            return []
        want = [s for s in missing if got is not None and got.get(s) not in router.RESIDENT and s not in asked]
        if want:
            asked.update(interactive.load(want, base, _poster(base, post)))
        if clock() >= end:
            return missing
        sleep(interactive.WARM_POLL_S)


@contextlib.contextmanager
def opened(hold_s: float | None, why: str, *, get=None, post=None, sleep=time.sleep, clock=time.monotonic, say=print):
    """Send interactive work to a node or the cloud, release the pinned set for at most `hold_s`, then put it back."""
    if not hold_s:
        raise Refused("no engine bounds the screen, so the window could not be given an end")
    plan = interactive.read()
    stems = sorted({e["stem"] for e in (plan.get("lanes") or {}).values()})
    base, got = _status(plan, get)
    if not stems or not base:
        raise Refused("nothing is pinned here to release")
    if got is None or any(got.get(s) != "loaded" for s in stems):
        raise Refused(f"the pinned set is not all loaded now ({got}), so its restore could not be confirmed")
    gateway_switch.start_drain(time.time() + DRAIN_S + float(hold_s) + interactive.WARM_WAIT_S, node=interactive.WINDOW)
    missing: list[str] = []
    try:
        ask = interactive._ask(base, get) or (lambda path: router._get(path, base))
        start, busy = clock(), node_state._busy(ask, stems)
        while busy != 0 and clock() - start < DRAIN_S:
            sleep(interactive.WARM_POLL_S)
            busy = node_state._busy(ask, stems)
        if busy != 0:
            cuts.cut("screen_window_drain", f"{why}: interactive requests still in flight", kept=0, dropped=1)
            raise Refused(f"the interactive server still had {'unknown' if busy is None else busy} request(s) "
                          f"in flight after {DRAIN_S:g} s")
        router.release(stems, why, get=interactive._ask(base, get), post=_poster(base, post), keep=set(),
                       say=say, base=base, proven_idle=True)
        _, got = _status(plan, get)
        kept = [s for s in stems if got is None or got.get(s) in router.RESIDENT]
        if kept:
            raise Refused(f"{', '.join(kept)} stayed resident on the interactive server")
        say(f"   window: released {', '.join(stems)} for at most {float(hold_s):.0f} s; interactive work goes to "
            f"a node or the cloud")
        yield stems
    finally:
        missing = restore(plan, get, post, sleep, clock)
        gateway_switch.stop_drain(node=interactive.WINDOW)
        say(f"   window: {'restored ' + ', '.join(stems) if not missing else 'NOT restored: ' + ', '.join(missing)}")
    if missing:
        raise Refused(f"{', '.join(missing)} did not load back in {interactive.WARM_WAIT_S:g} s")
