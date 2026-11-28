"""Continuous paired test and power plan for lanes scored on an error rate (WER/CER) (#2181)."""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from statistics import NormalDist

#: Lanes whose primary score is a per-case error rate, and that rate's metric name.
METRIC = {"stt": "wer", "tts": "wer", "ocr": "cer"}
#: The drop in the metric (absolute, in the metric's own units) worth a model switch, per lane.
EFFECT = {"stt": 0.02, "tts": 0.03, "ocr": 0.05}
#: The drop assumed for a lane scored on an error rate that EFFECT does not name.
DEFAULT_EFFECT = 0.02
#: Correlation assumed between two models' per-case scores until a pair measures it.
CORR = 0.4
#: Pitman efficiency of the signed-rank test against the paired t-test at the normal.
ARE = 0.955
#: Up to this many non-tied cases the signed-rank p is the exact permutation sum, above it the tie-corrected normal.
EXACT_N = 30
#: The per-draw spread assumed for an incumbent with no stored draws, whose plan never closes its lane.
UNMEASURED_SD = 0.1
#: A per-case score is held to [0, SCORE_CAP], so one runaway transcript cannot outweigh the cases.
SCORE_CAP = 1.0


def metric_of(lane: str) -> str:
    return METRIC.get((lane or "").strip().lower(), "")


def effect_for(lane: str) -> float:
    return EFFECT.get((lane or "").strip().lower(), DEFAULT_EFFECT) if metric_of(lane) else 0.0


def _value(row: dict, metric: str):
    got = row.get("metrics")
    if isinstance(got, str):
        try:
            got = json.loads(got or "{}")
        except ValueError:
            got = {}
    value = (got or {}).get(metric)
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def scores(rows, candidate: str, metric: str) -> dict[str, list[float]]:
    """base case -> the candidate's judged draws of `metric`, capped; a judged row without it scores the cap."""
    from harness import holdout, paired
    got: dict[str, list[float]] = {}
    for r in rows:
        if r.get("candidate") != candidate or paired._verdict(r) is None:
            continue
        v = _value(r, metric)
        got.setdefault(holdout.base_id(r.get("case_id")), []).append(
            SCORE_CAP if v is None else min(SCORE_CAP, max(0.0, v)))
    return got


def differences(rows, inc: str, ch: str, metric: str) -> tuple[dict[str, float], int]:
    """(case -> incumbent's mean less challenger's mean, so a gain is positive; paired draws behind them)."""
    a, b = scores(rows, inc, metric), scores(rows, ch, metric)
    keys = sorted(a.keys() & b.keys())
    return ({k: statistics.fmean(a[k]) - statistics.fmean(b[k]) for k in keys},
            sum(min(len(a[k]), len(b[k])) for k in keys))


def signed_rank(diffs) -> tuple[float, int, float]:
    """(W+, non-tied cases, two-sided p) of the Wilcoxon signed-rank test; zero differences carry nothing and drop out."""
    d = [x for x in diffs if abs(x) > 1e-12]
    n = len(d)
    if n == 0:
        return 0.0, 0, 1.0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    rank = [0.0] * n
    ties = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(abs(d[order[j + 1]]) - abs(d[order[i]])) <= 1e-12:
            j += 1
        for k in range(i, j + 1):
            rank[order[k]] = (i + j) / 2 + 1
        ties.append(j - i + 1)
        i = j + 1
    plus = sum(r for r, x in zip(rank, d) if x > 0)
    total = n * (n + 1) / 2
    if n <= EXACT_N:
        half = sorted(round(2 * r) for r in rank)
        counts = {0: 1}
        for w in half:
            nxt = dict(counts)
            for s, c in counts.items():
                nxt[s + w] = nxt.get(s + w, 0) + c
            counts = nxt
        mine = round(2 * plus)
        lo = sum(c for s, c in counts.items() if s <= mine)
        hi = sum(c for s, c in counts.items() if s >= mine)
        return plus, n, min(1.0, 2 * min(lo, hi) / 2 ** n)
    mean = total / 2
    var = n * (n + 1) * (2 * n + 1) / 24 - sum(t ** 3 - t for t in ties) / 48
    if var <= 0:
        return plus, n, 1.0
    step = 1.0 if max(ties) == 1 else 0.5
    z = max(0.0, abs(plus - mean) - step / 2) / math.sqrt(var)
    return plus, n, min(1.0, 2 * (1 - NormalDist().cdf(z)))


def cell(rows, inc: str, ch: str, lane: str):
    """The two candidates paired by case on the lane's error rate: a Cell whose p is the signed-rank test and whose shift is the mean drop; rows that carry no such metric pair on pass bits. #2181."""
    from harness import paired
    metric = metric_of(lane)
    if not any(_value(r, metric) is not None for r in rows if r.get("candidate") in (inc, ch)):
        return paired.head_to_head(rows, inc, ch)
    diffs, draws = differences(rows, inc, ch, metric)
    if not diffs:
        mine = {r.get("candidate") for r in rows}
        return paired.Cell(ch, 0, 0, 0, refused="" if {inc, ch} <= mine else "the two candidates share no case")
    gained = sum(x > 1e-12 for x in diffs.values())
    lost = sum(x < -1e-12 for x in diffs.values())
    _, _, p = signed_rank(diffs.values())
    return paired.Cell(ch, lost, gained, len(diffs) - gained - lost, p_value=p,
                       shift=statistics.fmean(diffs.values()), draws=draws)


@dataclass(frozen=True)
class Model:
    """What the plan knows of a lane's per-draw scores: the incumbent's spread, and how alike two models' cases score."""
    metric: str
    sd: float
    corr: float = CORR

    @property
    def sd_diff(self) -> float:
        return self.sd * math.sqrt(2.0 * (1.0 - self.corr))

    def power_cells(self, n: int, effect: float, alpha: float) -> float:
        """P(the signed-rank test adopts) over n independent cells when the challenger's error is lower by `effect`."""
        if n < 1 or effect <= 0 or self.sd_diff <= 0:
            return 0.0
        z = NormalDist().inv_cdf(1 - alpha / 2)
        return NormalDist().cdf(effect / self.sd_diff * math.sqrt(ARE * n) - z)

    def as_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def of(got: dict | None) -> "Model | None":
        return Model(got["metric"], float(got["sd"]), float(got.get("corr", CORR))) if got else None


def model_from(draws: dict, metric: str, corr: float = CORR) -> Model | None:
    """The incumbent's per-draw spread of `metric` over its stored draws (case -> list of scores); None when it has none."""
    flat = [x for v in draws.values() for x in v]
    if len(flat) < 2:
        return None
    return Model(metric, statistics.pstdev(flat), corr)


def model_for(draws: dict, holdout_ids, metric: str) -> Model:
    """The plan's model from the incumbent's scored draws on the holdout, or the unmeasured spread when it has none."""
    return model_from({c: draws[c] for c in holdout_ids if draws.get(c)}, metric) or Model(metric, UNMEASURED_SD)


def conditional_power(shift: float, done: int, planned: int, effect: float, sd_diff: float, alpha: float) -> float:
    """P(the final signed-rank test adopts) from `done` of `planned` cases at mean paired gain `shift`, the rest going at `effect`."""
    if planned <= 0 or sd_diff <= 0:
        return 0.0
    z = NormalDist().inv_cdf(1 - alpha / 2)
    left = planned - done
    need = z * sd_diff * math.sqrt(planned / ARE)
    have = shift * done
    if left <= 0:
        return 1.0 if have >= need else 0.0
    return 1.0 - NormalDist().cdf((need - have - left * effect) / (sd_diff * math.sqrt(left)))


#: Holdout sizes a replay's bootstrap tries, in order, for the cases each test needs.
GRID = (40, 60, 80, 100, 134, 170, 220, 280, 360, 460, 600, 800, 1100, 1500, 2000, 3000)
TESTS = ("sign_pass", "sign_metric", "signed_rank")


def _sign_p(vals) -> float:
    from harness import paired
    g = sum(x > 1e-12 for x in vals)
    lost = sum(x < -1e-12 for x in vals)
    return paired.sign_test(min(g, lost), g + lost)


def _pass_bits(rows, candidate: str) -> dict[str, float]:
    from harness import holdout, paired
    got: dict[str, list[int]] = {}
    for r in rows:
        if r.get("candidate") == candidate and paired._verdict(r) is not None:
            got.setdefault(holdout.base_id(r.get("case_id")), []).append(int(bool(r.get("passed"))))
    return {k: statistics.fmean(v) for k, v in got.items()}


def _pvalues(pairs) -> dict[str, float]:
    """p of each test over (metric difference, pass-bit difference) per case."""
    return {"sign_pass": _sign_p([b for _, b in pairs]), "sign_metric": _sign_p([m for m, _ in pairs]),
            "signed_rank": signed_rank([m for m, _ in pairs])[2]}


def replay(rows, inc: str, ch: str, lane: str, *, reps: int = 200, seed: int = 0, alpha: float | None = None) -> dict:
    """A stored pair under the three tests: observed p, the holdout each needs for power 0.8 by bootstrap, and the sign-flipped null's false-positive rate. #2181."""
    import random
    from harness import adopt, power
    alpha = adopt.ALPHA if alpha is None else alpha
    metric = metric_of(lane)
    diffs, _ = differences(rows, inc, ch, metric)
    a, b = _pass_bits(rows, inc), _pass_bits(rows, ch)
    pairs = [(d, b[k] - a[k]) for k, d in diffs.items() if k in a and k in b]
    if not pairs:
        return {"cases": 0}
    rng = random.Random(seed)
    observed = _pvalues(pairs)

    def hits(n: int, flip: bool) -> dict[str, float]:
        won = dict.fromkeys(TESTS, 0)
        for _ in range(reps):
            draw = [rng.choice(pairs) for _ in range(n)]
            if flip:
                draw = [(m, g) if rng.random() < 0.5 else (-m, -g) for m, g in draw]
            if statistics.fmean(m for m, _ in draw) <= 0:
                continue
            for name, p in _pvalues(draw).items():
                won[name] += p <= alpha
        return {k: v / reps for k, v in won.items()}

    needed: dict[str, int | None] = dict.fromkeys(TESTS)
    for n in GRID:
        if all(v is not None for v in needed.values()):
            break
        got = hits(n, False)
        for name in TESTS:
            if needed[name] is None and got[name] >= power.TARGET:
                needed[name] = n
    shift = statistics.fmean(m for m, _ in pairs)
    return {"cases": len(pairs), "shift": shift, "mean_pass_lift": statistics.fmean(g for _, g in pairs),
            "p": observed, "cases_needed": needed, "null_rate": hits(len(pairs), True)}


def stored_rows(conn, lane: str) -> list[dict]:
    """The lane's stored measure rows on its holdout cases, as the paired helpers read them."""
    from harness import holdout
    ids = set(holdout.for_lane(lane).holdout)
    got = conn.execute("SELECT x.candidate, x.case_id, x.passed, x.failure_class, x.metrics FROM results x "
                       "JOIN runs u ON u.id = x.run_id WHERE u.lane = ? AND u.tier = 'measure'",
                       ((lane or "").strip().lower(),)).fetchall()
    return [dict(r) for r in got if holdout.base_id(r["case_id"]) in ids]


def replays(rows, lane: str, incumbent: str, challengers=(), *, floor: int = 100, reps: int = 200) -> list[dict]:
    """replay() of `incumbent` against each challenger, else every candidate with `floor` holdout cases, then against itself as the control."""
    metric = metric_of(lane)
    names = list(challengers) or sorted(
        {r["candidate"] for r in rows} - {incumbent},
        key=lambda c: (-len(scores(rows, c, metric)), c))
    out = []
    for name in [*names, incumbent]:
        if len(differences(rows, incumbent, name, metric)[0]) >= floor:
            out.append({"incumbent": incumbent, "challenger": name, "control": name == incumbent,
                        **replay(rows, incumbent, name, lane, reps=reps)})
    return out
