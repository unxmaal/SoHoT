"""Expected gain per GPU-minute for each measure-queue row, from stored paired cells, screens and pair_cost (#1315)."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from harness import lanes, methods

#: Prior mean of a challenger's per-cell net gain (gained minus lost per cell) over the incumbent.
PRIOR_MEAN = -0.05
#: Prior sd of that gain, before any evidence.
PRIOR_SD = 0.3
#: Cells of evidence the prior is worth: per-cell variance over PRIOR_SD squared.
PRIOR_CELLS = 2.0
#: Cells one paired comparison of a relative (same method head, or same family) tends to as its run grows.
RELATED_CELLS = 4.0

#: What a store read can raise when the store is a stub, missing a table, or older than this code.
_STORE_ERRORS = (AttributeError, sqlite3.Error, KeyError, TypeError)


@dataclass(frozen=True)
class Comparison:
    """One stored paired measure run of a proposal against the incumbent, recomputed from its rows."""
    run_id: int
    lane: str
    name: str
    gained: int
    lost: int
    cells: int
    at: float


@dataclass(frozen=True)
class Evidence:
    net: float
    cells: float
    source: str


@dataclass(frozen=True)
class Gain:
    name: str
    lane: str
    mean: float
    sd: float
    effect: float
    expected: float
    minutes: float | None
    evidence: tuple = ()
    why: str = ""

    @property
    def key(self) -> float | None:
        """Expected gain per GPU-minute; None when the row has no price."""
        return None if not self.minutes else self.expected / self.minutes

    def line(self) -> str:
        cost = f"{self.minutes:.0f} min" if self.minutes else f"unpriced ({self.why})"
        key = f"{self.key * 60:.4f}/h" if self.key is not None else "-"
        seen = ", ".join(e.source for e in self.evidence) or "no stored evidence"
        return (f"{self.name} ({self.lane}): gain {self.expected:.4f}/cell above +{self.effect:.2f} "
                f"(mean {self.mean:+.3f}, sd {self.sd:.3f}) over {cost}, key {key}; {seen}")


@dataclass
class Context:
    """What scoring every row of one queue reads once."""
    conn: object
    before: float | None = None
    comparisons: list = field(default_factory=list)
    standing: object = None
    rates: dict = field(default_factory=dict)
    costs: dict = field(default_factory=dict)


def _cutoff(before: float | None) -> float:
    return math.inf if before is None else float(before)


def comparisons(conn, before: float | None = None) -> list[Comparison]:
    """Every paired measure run a proposal's adopt verdict or pause names, decided before `before`, from its rows."""
    from harness import adopt
    cut = _cutoff(before)
    try:
        links = conn.execute(
            "SELECT v.run_id, p.name, v.decided_at AS at FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
            "WHERE v.tier = ? AND v.run_id IS NOT NULL "
            "UNION ALL SELECT run_id, proposal, paused_at FROM paused_runs WHERE run_id IS NOT NULL AND proposal <> ''",
            (adopt.TIER,)).fetchall()
    except _STORE_ERRORS:
        return []
    first: dict = {}
    for run_id, name, at in links:
        if at is not None and float(at) < cut and (run_id, name) not in first:
            first[(run_id, name)] = float(at)
    out = []
    for (run_id, name), at in sorted(first.items(), key=lambda kv: kv[1]):
        got = _compare(conn, run_id, name, at, cut)
        if got is not None:
            out.append(got)
    return out


def _compare(conn, run_id: int, name: str, at: float, cut: float) -> Comparison | None:
    """The run's challenger rows (its candidate names the proposal) paired with its one other key's."""
    import json

    from harness import adopt
    run = conn.execute("SELECT lane, recorded_at FROM runs WHERE id = ? AND tier = 'measure'", (run_id,)).fetchone()
    if run is None or float(run[1] or 0) >= cut:
        return None
    rows = conn.execute(
        "SELECT x.candidate, x.case_id, x.passed, x.metrics, x.failure_class, p.name FROM results x "
        "LEFT JOIN candidates c ON c.id = x.candidate_id LEFT JOIN proposals p ON p.id = c.proposal_id "
        "WHERE x.run_id = ? ORDER BY x.seq", (run_id,)).fetchall()
    keys = {r[0] for r in rows}
    mine = {r[0] for r in rows if r[5] == name}
    if len(keys) != 2 or len(mine) != 1:
        return None
    (ch,), (inc,) = mine, keys - mine
    lane = lanes.canonical(run[0])
    got = [{"candidate": r[0], "case_id": r[1], "passed": bool(r[2]), "metrics": json.loads(r[3] or "{}"),
            "failure_class": r[4] or ""} for r in rows]
    cell = adopt.lane_cell(got, inc, ch, lane, "challenger")
    cells = cell.gained + cell.lost + cell.unchanged
    return Comparison(run_id, lane, name, cell.gained, cell.lost, cells, at) if cells else None


def _head(name: str) -> str:
    parsed = methods.parse(name)
    return parsed.method.name if parsed is not None else ""


def related(row_name: str, lane: str, c: Comparison, standing) -> str:
    """How comparison `c` bears on `row_name` in `lane`: 'own', 'method', 'family', or '' when it does not."""
    if c.lane != lane:
        return ""
    if c.name == row_name:
        return "own"
    head = _head(row_name)
    if head:
        return "method" if _head(c.name) == head else ""
    if _head(c.name) or standing is None:
        return ""
    return "family" if standing.key_of(c.name) == standing.key_of(row_name) else ""


def screen_rows(conn, name: str, lane: str, before: float | None = None) -> list[dict]:
    """The proposal's screen rows in `lane` recorded before `before`; a screen runs the challenger alone."""
    import json
    cut = _cutoff(before)
    try:
        got = conn.execute(
            "SELECT x.case_id, x.passed, x.metrics, u.recorded_at FROM results x JOIN runs u ON u.id = x.run_id "
            "JOIN candidates c ON c.id = x.candidate_id JOIN proposals p ON p.id = c.proposal_id "
            "WHERE u.tier = 'screen' AND u.lane = ? AND p.name = ? ORDER BY x.id", (lane, name)).fetchall()
    except _STORE_ERRORS:
        return []
    return [{"case_id": r[0], "passed": bool(r[1]), "metrics": json.loads(r[2] or "{}")}
            for r in got if float(r[3] or 0) < cut]


def incumbent_rates(conn, lane: str) -> dict[str, float]:
    """The served incumbent's stored pass rate per base case, on the lane's metric; {} unmeasured."""
    from harness import screen
    try:
        draws = screen.incumbent_draws(lane, conn)
    except _STORE_ERRORS:
        return {}
    return {k: sum(v) / len(v) for k, v in draws.items() if v}


def screen_evidence(rows: list[dict], rates: dict, lane: str) -> Evidence | None:
    """The screen's draws against the incumbent's rate on the same cases; None when no case is shared."""
    from harness import holdout, power
    pairs = [(power.draw(r, lane), rates[holdout.base_id(r["case_id"])]) for r in rows
             if holdout.base_id(r["case_id"]) in rates]
    if not pairs:
        return None
    return Evidence(sum(d - p for d, p in pairs), float(len(pairs)), f"screen {len(pairs)} case(s)")


def evidence(ctx: Context, name: str, lane: str) -> list[Evidence]:
    """Own paired cells and screen at full weight; a relative's n paired cells count n*R/(n+R), R = RELATED_CELLS."""
    out = []
    for c in ctx.comparisons:
        how = related(name, lane, c, ctx.standing)
        if not how:
            continue
        # A relative's cells tell its own gain; the spread between members leaves RELATED_CELLS at most for this one.
        cells = c.cells if how == "own" else c.cells * RELATED_CELLS / (c.cells + RELATED_CELLS)
        out.append(Evidence((c.gained - c.lost) * cells / c.cells, float(cells),
                            f"{how} run {c.run_id} {c.gained}/{c.lost} of {c.cells}"))
    if lane not in ctx.rates:
        ctx.rates[lane] = incumbent_rates(ctx.conn, lane)
    got = screen_evidence(screen_rows(ctx.conn, name, lane, ctx.before), ctx.rates[lane], lane)
    if got is not None:
        out.append(got)
    return out


def posterior(evs) -> tuple[float, float]:
    """Mean and sd of the per-cell net gain: prior PRIOR_MEAN worth PRIOR_CELLS cells, sd PRIOR_SD."""
    n = sum(e.cells for e in evs)
    mean = (PRIOR_MEAN * PRIOR_CELLS + sum(e.net for e in evs)) / (PRIOR_CELLS + n)
    return mean, PRIOR_SD * math.sqrt(PRIOR_CELLS / (PRIOR_CELLS + n))


def expected_gain(mean: float, sd: float, effect: float) -> float:
    """E[max(0, gain - effect)] under Normal(mean, sd): a gain the gate cannot adopt is worth nothing."""
    if sd <= 0:
        return max(0.0, mean - effect)
    z = (mean - effect) / sd
    return sd * math.exp(-z * z / 2) / math.sqrt(2 * math.pi) + (mean - effect) * 0.5 * math.erfc(-z / math.sqrt(2))


def minutes(conn, row: dict, lane: str) -> tuple[float | None, str]:
    """GPU-minutes one measurement takes: holdout cases x pair_cost seconds per call x its calls; None, why if unpriced."""
    from harness import adopt, holdout, screen, winners
    from harness.commands import measure as measure_cmd
    cases = len(holdout.for_lane(lane).holdout)
    if not cases:
        return None, f"the {lane} lane has no holdout cases"
    incumbent = adopt.default_for(lane, winners.typed().get(lane, ""), conn=conn)
    if not incumbent:
        return None, f"the {lane} lane has no incumbent"
    inc_spec = screen.candidate_for(lane, incumbent) or incumbent
    spec = screen.candidate_for(lane, row.get("name", ""), row.get("attaches_to") or "", conn=conn) or ""
    if not spec:
        return None, "no candidate spec"
    _, per_call, calls, _ = measure_cmd.priced(conn, lane, inc_spec, spec)
    if per_call is None:
        return None, "no stored or estimated seconds per call"
    return cases * per_call * calls / 60.0, ""


def context(conn, before: float | None = None) -> Context:
    from harness import family
    return Context(conn, before, comparisons(conn, before), family.standing(conn))


def score(ctx: Context, row: dict, want: str = "") -> Gain:
    from harness import power
    from harness.commands import measure as measure_cmd
    name = row.get("name", "")
    lane = measure_cmd.lane_for(row, want)
    evs = evidence(ctx, name, lane)
    mean, sd = posterior(evs)
    effect = power.effect_for(lane)
    key = (name, lane)
    if key not in ctx.costs:
        try:
            ctx.costs[key] = minutes(ctx.conn, row, lane)
        except (*_STORE_ERRORS, ValueError, OSError) as exc:
            ctx.costs[key] = (None, f"pricing failed: {exc}")
    mins, why = ctx.costs[key]
    return Gain(name, lane, mean, sd, effect, expected_gain(mean, sd, effect), mins, tuple(evs), why)


def order(conn, rows, want: str = "", before: float | None = None, ctx: Context | None = None) -> tuple[list, list]:
    """Rows by expected gain per GPU-minute, highest first, unpriced last; ties keep their order. Returns (rows, gains)."""
    rows = list(rows)
    ctx = ctx or context(conn, before)
    gains = [score(ctx, r, want) for r in rows]
    at = sorted(range(len(rows)), key=lambda i: (gains[i].key is None, -(gains[i].key or 0.0), i))
    return [rows[i] for i in at], [gains[i] for i in at]
