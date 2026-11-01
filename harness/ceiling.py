"""A discover sweep's wall-clock ceiling: where its measurements pause for the next sweep. #806, #813."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

#: Ceiling seconds a finished sweep may leave unused before the morning report names why. #1082.
UNUSED_S = 3600.0
#: Seconds one screen is taken to need when the store holds no screens to measure it by. #1084.
SCREEN_S = 600.0
#: Share of a sweep's ceiling its screens may take; the measure step has the rest. #1084.
SCREEN_FRACTION = 0.5
#: Days of screens the per-screen estimate reads.
SCREEN_DAYS = 30


@dataclass
class Sweep:
    """One loop's ceiling, and what its measure step paused, resumed, stopped early or found stale."""
    ceiling_s: float
    clock: object = time.time
    started: float = 0.0
    lines: list = field(default_factory=list)
    #: Set when a run was paused on request: the sweep starts nothing more. #810.
    halted: str = ""
    #: Set when a run was paused for memory: the sweep goes on with what fits. #1082.
    squeezed: str = ""
    #: Why the measure step started nothing more, and how many measurements it left waiting. #1082.
    stopped: str = ""
    waiting: int = 0

    def __post_init__(self):
        self.started = self.started or self.clock()

    def remaining(self) -> float:
        return max(0.0, self.started + self.ceiling_s - self.clock())

    def unused(self, record: bool = True) -> dict | None:
        """The ceiling this sweep left unused and why, when it is more than UNUSED_S; None otherwise."""
        left = self.remaining()
        if left <= UNUSED_S:
            if record and left > 0:
                from harness import cuts
                cuts.cut("sweep_unused_s", f"{left:.0f} s of the sweep ceiling left unused, too little to report",
                         kept=0, dropped=1)
            return None
        return {"ceiling_s": self.ceiling_s, "left_s": round(left), "waiting": self.waiting,
                "why": self.stopped or "the measure step ran out of measurements"}

    def summary(self) -> list[str]:
        from harness import power
        at = time.strftime("%H:%M", time.localtime(self.started))
        out = ["\n=== sweep ceiling ===",
               f"  {power._hm(self.ceiling_s)} from {at}, {power._hm(self.remaining())} left"]
        out += [f"  {line}" for line in self.lines]
        got = self.unused(record=False)
        if got:
            out.append(f"  unused: {power._hm(got['left_s'])} of the ceiling: {got['why']}")
        return out


def screen_s(conn, now: float | None = None, days: float | None = None) -> float:
    """Mean seconds from one screen verdict to the next screen that ran within a sweep, or SCREEN_S. #1084."""
    from harness import power
    now = time.time() if now is None else now
    days = SCREEN_DAYS if days is None else days
    rows = conn.execute("SELECT decided_at, run_id FROM verdicts WHERE tier = 'screen' AND decided_at >= ? "
                        "ORDER BY decided_at, id", (now - days * 86400,)).fetchall()
    sweep_s = float(power.SWEEP_CEILING_H) * 3600
    gaps = [b[0] - a[0] for a, b in zip(rows, rows[1:]) if b[1] and 0 < b[0] - a[0] <= sweep_s]
    return sum(gaps) / len(gaps) if gaps else float(SCREEN_S)


def screens_that_fit(seconds: float, per_s: float) -> int:
    """How many screens of `per_s` seconds each fit in `seconds`."""
    return max(0, int(seconds // per_s)) if per_s > 0 else 0


def screen_capacity(conn, seconds: float | None = None, now: float | None = None) -> int:
    """Screens one sweep has room for: its ceiling's screen share over the measured seconds per screen. #1084."""
    from harness import power
    seconds = float(power.SWEEP_CEILING_H) * 3600 if seconds is None else seconds
    return screens_that_fit(seconds * SCREEN_FRACTION, screen_s(conn, now))
