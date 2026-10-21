"""A discover sweep's wall-clock ceiling: where its measurements pause for the next sweep. #806, #813."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

#: Ceiling seconds a finished sweep may leave unused before the morning report names why. #1082.
UNUSED_S = 3600.0


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

    def unused(self) -> dict | None:
        """The ceiling this sweep left unused and why, when it is more than UNUSED_S; None otherwise."""
        left = self.remaining()
        if left <= UNUSED_S:
            return None
        return {"ceiling_s": self.ceiling_s, "left_s": round(left), "waiting": self.waiting,
                "why": self.stopped or "the measure step ran out of measurements"}

    def summary(self) -> list[str]:
        from harness import power
        at = time.strftime("%H:%M", time.localtime(self.started))
        out = ["\n=== sweep ceiling ===",
               f"  {power._hm(self.ceiling_s)} from {at}, {power._hm(self.remaining())} left"]
        out += [f"  {line}" for line in self.lines]
        got = self.unused()
        if got:
            out.append(f"  unused: {power._hm(got['left_s'])} of the ceiling: {got['why']}")
        return out
