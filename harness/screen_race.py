"""A screen as a paired sequential race against the incumbent's stored cells: the Beta-binomial posterior, its stopping rule and the cases' order (#2166)."""
from __future__ import annotations

import math
import statistics
import sys
from dataclasses import dataclass, field

#: Posterior chance the challenger beats the incumbent by the adopt effect under which a race declines it.
SCREEN_FUTILITY = 0.05
#: Posterior chance over which a race passes the challenger before its case cap.
SCREEN_PROMISE = 0.5
#: The Beta prior on the gained share of discordant pairs: one gained and one lost, worth two cells.
PRIOR = 1.0
#: The race's own record in a screen summary row, read back by screen.outcome.
KEY = "screen_race"
PASS, DECLINE, CAP = "pass", "decline", "cap"


def target(effect: float) -> float:
    """The gained share of discordant pairs a challenger must exceed to beat the incumbent by `effect`."""
    return 0.5 + effect / 2.0


def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        for num in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                    -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1.0 + num * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + num / (c if abs(c) > tiny else tiny)
            h *= d * c
        if abs(d * c - 1.0) < 1e-12:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    """P(Beta(a, b) <= x), the regularised incomplete beta function."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def posterior(gained: float, lost: float, effect: float) -> float:
    """P(gained share of discordant pairs > 0.5 + effect / 2) with the share ~ Beta(PRIOR + gained, PRIOR + lost)."""
    return 1.0 - beta_cdf(target(effect), PRIOR + gained, PRIOR + lost)


def pair(passed: bool, rate: float) -> tuple[float, float]:
    """(gained, lost) one challenger draw makes against the incumbent's stored draws on its case, whose pass rate is `rate`."""
    return (1.0 - rate, 0.0) if passed else (0.0, rate)


def decide(p: float, cases: int, cap: int, futility: float, promise: float) -> str:
    """'decline' under futility, 'pass' over promise, 'cap' at the case cap, else '' to run another case."""
    if p < futility:
        return DECLINE
    if p > promise:
        return PASS
    return CAP if cases >= cap else ""


@dataclass(frozen=True)
class Plan:
    """What one lane's race runs on: its cases in weed-out order, the incumbent's rate on each, the effect and the three limits."""
    lane: str
    order: tuple
    rates: dict
    effect: float
    futility: float
    promise: float
    cap: int


@dataclass
class Race:
    plan: Plan
    gained: float = 0.0
    lost: float = 0.0
    cases: int = 0
    decision: str = ""
    seen: set = field(default_factory=set)

    @property
    def p(self) -> float:
        return posterior(self.gained, self.lost, self.plan.effect)

    def add(self, case_id: str, passed: bool) -> str:
        """Fold one finished case in; the decision once the race is over, else ''. A case the incumbent has no cell for is not paired."""
        from harness import holdout
        base = holdout.base_id(case_id)
        if self.decision or base in self.seen or base not in self.plan.rates:
            return self.decision
        self.seen.add(base)
        g, lo = pair(passed, self.plan.rates[base])
        self.gained, self.lost, self.cases = self.gained + g, self.lost + lo, self.cases + 1
        self.decision = decide(self.p, self.cases, self.plan.cap, self.plan.futility, self.plan.promise)
        return self.decision

    def record(self) -> dict:
        return {"cases": self.cases, "gained": round(self.gained, 4), "lost": round(self.lost, 4),
                "posterior": round(self.p, 4), "decision": self.decision or CAP, "effect": self.plan.effect,
                "futility": self.plan.futility, "promise": self.plan.promise, "cap": self.plan.cap}

    def line(self) -> str:
        r = self.record()
        return (f"raced {r['cases']} case(s) against the incumbent's stored cells: gained {r['gained']:g}, "
                f"lost {r['lost']:g}, P(beats it by {r['effect']:g}) {r['posterior']:.3f}")


def stored(lane: str, conn) -> tuple[dict, dict]:
    """(case -> the served incumbent's stored pass rate, case -> its mean seconds), one read of its rows."""
    from harness import holdout, power, winners
    cid = winners.served_ids(conn).get(lane)
    if cid is None:
        return {}, {}
    draws, rows = power._served_rows(conn, lane, "", cid, False)
    secs: dict[str, list[float]] = {}
    for r in rows:
        if r["seconds"] is not None:
            secs.setdefault(holdout.base_id(r["case_id"]), []).append(float(r["seconds"]))
    return ({c: sum(v) / len(v) for c, v in draws.items() if v},
            {c: statistics.fmean(v) for c, v in secs.items()})


def plan(lane: str, case_ids, cap: int, conn=None) -> Plan | None:
    """The race over `case_ids` in weed-out order, or None when the incumbent has no stored cell on any of them."""
    from harness import holdout, power, runs, screen, weedout
    lane = (lane or "").strip().lower()
    if lane in screen.WER_SCREENED or lane in screen.MEDIA_LANES:
        return None
    try:
        with runs.store(conn) as c:
            rates, secs = stored(lane, c)
    except Exception as exc:  # noqa: BLE001 - no store reads as no cells
        print(f"screen: could not read the {lane} incumbent's cells for a race: {exc}", file=sys.stderr)
        return None
    ids = list(dict.fromkeys(holdout.base_id(i) for i in case_ids))
    ids = [i for i in ids if i in rates]
    if not ids:
        return None
    effect = power.effect_for(lane)
    return Plan(lane, tuple(weedout.order(ids, rates, secs, effect)), {i: rates[i] for i in ids}, effect,
                SCREEN_FUTILITY, SCREEN_PROMISE, int(cap))


def replay(rows, rates: dict, lane: str, effect: float) -> Race:
    """The race over a screen's stored rows in the order they ran, against stored incumbent rates, at today's limits and no cap."""
    race = Race(Plan(lane, tuple(rates), dict(rates), effect, SCREEN_FUTILITY, SCREEN_PROMISE, len(rows)))
    for r in rows:
        race.add(r["case_id"], bool(r["passed"]))
    return race

