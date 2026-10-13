"""A discover sweep's wall-clock ceiling, and the lead a measurement may spend the rest of it on. #806."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Lead:
    """An underpowered verdict that leaned to the challenger, from its run's holdout rows."""
    gained: int
    lost: int
    p: float
    at: float

    def text(self) -> str:
        return (f"lead: {self.gained} gained vs {self.lost} lost, p={self.p:.2f} "
                f"on {time.strftime('%Y-%m-%d', time.localtime(self.at))}")


@dataclass
class Sweep:
    """One loop's ceiling, the leads it has extended, and what its measure step refused or extended."""
    ceiling_s: float
    clock: object = time.time
    started: float = 0.0
    spent: set = field(default_factory=set)
    lines: list = field(default_factory=list)

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


def key(lane: str, inc_spec: str, spec: str) -> tuple[str, str, str]:
    return ((lane or "").strip().lower(), inc_spec, spec)


def lead(conn, lane: str, inc_spec: str, spec: str) -> Lead | None:
    """The pairing's last adopt verdict as a lead: underpowered, gained > lost, paired p < power.LEAD_P."""
    from harness import adopt, candidates, holdout, power, reasons, runs
    lane = (lane or "").strip().lower()
    row = candidates.get(conn, spec)
    if not row or row["spec"] != spec:
        return None
    # An inconclusive verdict (refused or stopped, #673, #796) decided nothing, so it cannot end a lead.
    v = conn.execute("SELECT failure_class, run_id, split_version, decided_at FROM verdicts "
                     "WHERE tier = ? AND candidate_id = ? AND failure_class != ? ORDER BY id DESC LIMIT 1",
                     (adopt.TIER, row["id"], reasons.INCONCLUSIVE)).fetchone()
    if not v or v["failure_class"] != reasons.UNDERPOWERED or v["run_id"] is None:
        return None
    split = holdout.for_lane(lane)
    if v["split_version"] and v["split_version"] != split.version:
        return None
    inc = candidates.get(conn, inc_spec)
    inc_key = inc["receipt_key"] if inc and inc["spec"] == inc_spec else candidates.key_of(inc_spec)
    got = holdout.rows_on(runs.rows(conn, v["run_id"]), split, "holdout")
    names = {r["candidate"] for r in got}
    if inc_key not in names or row["receipt_key"] not in names:
        return None   # a run against another incumbent is not this pairing
    cell, p, _ = adopt.paired_p(got, inc_key, row["receipt_key"], lane)
    if cell.gained <= cell.lost or p >= power.LEAD_P:
        return None
    return Lead(cell.gained, cell.lost, p, v["decided_at"])
