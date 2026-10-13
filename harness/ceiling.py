"""A discover sweep's wall-clock ceiling: where its measurements pause for the next sweep. #806, #813."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Sweep:
    """One loop's ceiling, and what its measure step paused, resumed, stopped early or found stale."""
    ceiling_s: float
    clock: object = time.time
    started: float = 0.0
    lines: list = field(default_factory=list)
    #: Set when a run was paused on request: the sweep starts nothing more. #810.
    halted: str = ""

    def __post_init__(self):
        self.started = self.started or self.clock()

    def remaining(self) -> float:
        return max(0.0, self.started + self.ceiling_s - self.clock())

    def summary(self) -> list[str]:
        from harness import power
        at = time.strftime("%H:%M", time.localtime(self.started))
        out = ["\n=== sweep ceiling ===",
               f"  {power._hm(self.ceiling_s)} from {at}, {power._hm(self.remaining())} left"]
        return out + [f"  {line}" for line in self.lines]
