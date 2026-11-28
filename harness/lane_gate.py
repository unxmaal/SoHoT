"""The lane gate: a lane whose power plan at its adopt effect is below lane_gate_power takes no challengers; the owner's recorded, expiring override (#2164)."""
from __future__ import annotations

import contextlib
import json
from threading import local as _Local
import time
from dataclasses import dataclass, replace

#: A lane whose plan power at its adopt effect is under this is closed to challengers. #2164.
GATE_POWER = 0.8
#: An open lane stays open until its power falls under this lower bar, so one night's draws cannot flip it. #2199.
STAY_POWER = 0.75
#: The file under the home that remembers each lane's last gate state.
STATE_FILE = "lane-gate-state.json"
#: How long the owner's "open anyway" lasts before the lane closes again. #2164.
OPEN_S = 3 * 86400.0
#: The holds row kind of an override, then the lane.
OPEN_KIND = "lane-open:"
GROWTH_ISSUE = "https://github.com/unxmaal/SoHoT/issues/603"
OWNER = "owner: from the status page"
#: A second reason to close a lane: its incumbent is marked down (incumbent_down); no override opens it. #2168.
DOWN = "incumbent_down"


@dataclass(frozen=True)
class Calc:
    """One lane's incumbent profile and the power plan at its adopt effect: what `soh adopt --power` and the gate both read."""
    key: str
    inc_spec: str
    draws: dict
    inc_s: float | None
    settings: tuple
    machines: list
    rates: dict
    seen: int
    effect: float
    tested: int
    alpha: float
    plan: object
    #: The pass/fail sign test's plan on the same holdout, kept beside a continuous lane's own for the report. #2181.
    sign_plan: object = None


@dataclass(frozen=True)
class Gate:
    lane: str
    power: float
    effect: float
    holdout: int
    cases_needed: int | None
    more_holdout: int | None
    more_cases: int | None
    kind: str = "power"
    detail: str = ""
    #: What the effect is a gain in: the metric of a continuous lane (its effect a drop in it), else "per cell". #2181.
    unit: str = "per cell"
    sign_cases_needed: int | None = None
    #: The power bar this lane was held to: STAY_POWER when it was open, else GATE_POWER. #2199.
    bar: float | None = None

    @property
    def why(self) -> str:
        if self.kind == DOWN:
            return f"{self.lane} lane closed to challengers: {self.detail}; soh reverify --lane {self.lane} clears it once it answers"
        need = ("no holdout size reaches it" if self.cases_needed is None else
                f"needs {self.more_holdout} more holdout cases ({self.cases_needed} in all, {self.holdout} here)")
        if self.unit != "per cell" and self.sign_cases_needed is not None:
            need += f"; the pass/fail sign test needed {self.sign_cases_needed}"
        return (f"{self.lane} lane closed to challengers: power {self.power:.2f} at {self.gain} is under "
                f"{'lane_gate_power' if self.bar in (None, GATE_POWER) else 'lane_gate_stay_power'} "
                f"{GATE_POWER if self.bar is None else self.bar:.2f}, {need}; soh lane-gate open {self.lane} overrides for a while")

    @property
    def gain(self) -> str:
        return f"+{self.effect:.2f}" if self.unit == "per cell" else f"-{self.effect:.2f} {self.unit}"

    def as_dict(self) -> dict:
        return {"lane": self.lane, "power": round(self.power, 4), "effect": self.effect, "holdout": self.holdout,
                "unit": self.unit, "sign_cases_needed": self.sign_cases_needed, "cases_needed": self.cases_needed, "more_holdout": self.more_holdout, "more_cases": self.more_cases,
                "why": self.why, "issue": GROWTH_ISSUE}


def _row(r: dict) -> dict:
    return {"candidate": r.get("candidate"), "case_id": r.get("case_id"),
            "passed": r.get("passed"), "seconds": r.get("seconds"), "metrics": r.get("metrics")}


def profile(lane: str, receipts: dict, conn, scored: bool | None = None) -> tuple[str, str, dict, float | None, tuple, list]:
    """(incumbent key, its spec, its draws per case, its median seconds here at the lane's budget, settings, machines); error rates, not pass bits, on a continuous lane unless `scored` is False."""
    from harness import adopt, candidates, continuous, power, reply_cap, runs, screen, winners
    scored = bool(continuous.metric_of(lane)) if scored is None else scored
    served = adopt.default_for(lane, winners.typed().get(lane, ""), conn)
    spec = (screen.candidate_for(lane, served) or served) if served else ""
    try:
        key = candidates.key_of(spec) if spec else ""
    except Exception:  # noqa: BLE001
        key = ""
    settings = (reply_cap.cap_for(conn, lane, [spec or served])[0], ())
    machines = runs.here(conn)
    if lane in receipts:
        sets = [[_row(r) for r in got["rows"]] for got in receipts[lane]]
        key = power.control_of(sets, prefer=[k for k in (key, spec, served) if k])
        draws, _ = power.draws_from([r for rows in sets for r in rows], key, lane, scored)
        timed = [_row(r) for got in receipts[lane] if power.receipt_here(got["environment"])
                 and power.reply_settings(json.dumps(got["receipt"]), lane) == settings for r in got["rows"]]
        return key, spec or served, draws, power.draws_from(timed, key)[1], settings, machines
    key = key or spec
    draws, median = (power.served_profile(conn, lane, spec, settings, machines, scored=scored)
                     if spec else ({}, None))
    return key, spec or served, draws, median, settings, machines


def calc(conn, lane: str, split, receipts: dict | None = None, effect: float | None = None) -> Calc:
    """The power plan over the lane's holdout at the incumbent's measured rates; `soh adopt --power` and the gate share it."""
    from evals.run import STOCHASTIC_MODALITIES
    from harness import adopt, continuous, power
    receipts = receipts or {}
    key, inc_spec, draws, inc_s, settings, machines = profile(lane, receipts, conn)
    rates, seen = power.rates_from(draws, split.holdout)
    rho = power.icc([list(draws.values())])
    metric = continuous.metric_of(lane)
    effect = effect or (continuous.effect_for(lane) if metric else power.effect_for(lane))
    tested = adopt.comparisons(conn, lane, split.version)
    alpha = adopt.alpha_for(tested)
    model = continuous.model_for(draws, split.holdout, metric) if metric else None
    plan = power.plan([rates[c] for c in split.holdout], effect, stochastic=lane in STOCHASTIC_MODALITIES,
                      observed=seen, rho=rho, alpha=alpha, unmeasured=not any(draws.values()), model=model)
    sign = None
    if metric:
        bits, _ = profile(lane, receipts, conn, scored=False)[2:4]
        bit_rates, bit_seen = power.rates_from(bits, split.holdout)
        sign = power.plan([bit_rates[c] for c in split.holdout], power.effect_for(lane),
                          stochastic=lane in STOCHASTIC_MODALITIES, observed=bit_seen, rho=power.icc([list(bits.values())]),
                          alpha=alpha, unmeasured=not any(bits.values()))
        plan = replace(plan, sign_cases_needed=sign.cases_needed)
    return Calc(key, inc_spec, draws, inc_s, settings, machines, rates, seen, effect, tested, alpha, plan, sign)


def closes(plan, threshold: float | None = None) -> bool:
    """Whether a plan closes its lane: measured rates, and power under the gate. An unmeasured plan is a guess and never closes."""
    return not plan.unmeasured and plan.power < (GATE_POWER if threshold is None else threshold)


def _state_path():
    from harness import paths
    return paths.home() / STATE_FILE


def _states() -> dict:
    try:
        got = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def was_open(lane: str) -> bool:
    """Whether the gate last left `lane` open; a lane it has not judged yet is held to the opening bar. #2199."""
    return _states().get(lane) == "open"


def _remember(lane: str, closed: bool) -> None:
    got = _states()
    now = "closed" if closed else "open"
    if got.get(lane) == now:
        return
    got[lane] = now
    try:
        to = _state_path()
        to.parent.mkdir(parents=True, exist_ok=True)
        to.write_text(json.dumps(got, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


_memo = _Local()


@contextlib.contextmanager
def remembered():
    """gate_for answers once per (store, lane) in this block: one status build asks for every lane's gate from two sections. #2191."""
    if getattr(_memo, "seen", None) is not None:
        yield
        return
    _memo.seen = {}
    try:
        yield
    finally:
        _memo.seen = None


def gate_for(conn, lane: str, split=None) -> Gate | None:
    """The gate on one lane from its power plan, whatever the owner's override says; None when it is open by power."""
    from harness import lanes
    seen = getattr(_memo, "seen", None)
    key = (id(conn), lanes.canonical(lane))
    if seen is not None and key in seen:
        return seen[key]
    got = _gate_for(conn, lane, split)
    if seen is not None:
        seen[key] = got
    return got


def _gate_for(conn, lane: str, split=None) -> Gate | None:
    import math

    from harness import holdout, lanes
    lane = lanes.canonical(lane)
    split = split or holdout.for_lane(lane)
    if not (split.dev or split.holdout):
        return None
    c = calc(conn, lane, split)
    bar = STAY_POWER if was_open(lane) else GATE_POWER
    low = closes(c.plan, bar)
    if not c.plan.unmeasured:
        _remember(lane, low)
    if not low:
        return None
    need = c.plan.cases_needed
    more = max(0, need - len(split.holdout)) if need else None
    from harness import power
    return Gate(lane, c.plan.power, c.effect, len(split.holdout), need, more,
                None if more is None else math.ceil(more / holdout.FRACTION),
                unit=power.unit_of(c.plan), sign_cases_needed=getattr(c.plan, "sign_cases_needed", None), bar=bar)


def override(conn, lane: str, now: float | None = None) -> dict | None:
    """The owner's override of `lane` in force at now, the latest; None when there is none."""
    from harness import hold, machine_scope
    now = time.time() if now is None else now
    if not hold._has(conn):
        return None
    where, args = machine_scope.here(conn, "holds.mine")
    r = conn.execute(f"SELECT * FROM holds WHERE {where} AND kind = ? AND released_at IS NULL AND held_at <= ? "
                     "AND until > ? ORDER BY until DESC LIMIT 1", (*args, OPEN_KIND + lane, now, now)).fetchone()
    return dict(r) if r else None


def open_lane(conn, lane: str, said: str = OWNER, now: float | None = None, ttl: float | None = None) -> dict:
    """Record that the owner opened `lane` to challengers until now + ttl; refused for a name that is no lane."""
    from harness import lanes
    from harness import memory_store as ms
    lane = lanes.canonical(lane)
    if lane not in lanes.ALL:
        raise ValueError(f"unknown lane {lane!r}; known: {', '.join(lanes.ALL)}")
    now = time.time() if now is None else now
    cur = conn.execute("INSERT INTO holds (machine_id, kind, held_at, said, until) VALUES (?,?,?,?,?)",
                       (ms.remember_machine(conn), OPEN_KIND + lane, now, " ".join(said.split()) or OWNER,
                        now + (OPEN_S if ttl is None else ttl)))
    conn.commit()
    return dict(conn.execute("SELECT * FROM holds WHERE id = ?", (cur.lastrowid,)).fetchone())


def close_lane(conn, lane: str, now: float | None = None) -> dict | None:
    """End the override of `lane` now; the override that was in force, or None."""
    from harness import lanes, machine_scope
    lane = lanes.canonical(lane)
    now = time.time() if now is None else now
    got = override(conn, lane, now)
    if got is None:
        return None
    where, args = machine_scope.here(conn, "holds.mine")
    conn.execute(f"UPDATE holds SET released_at = ? WHERE {where} AND kind = ? AND released_at IS NULL AND until > ?",
                 (now, *args, OPEN_KIND + lane, now))
    conn.commit()
    return {**got, "released_at": now}


def down_gate(lane: str) -> Gate | None:
    """The gate on `lane` while its incumbent is marked down; None with no mark. #2168."""
    from harness import incumbent_down, lanes
    m = incumbent_down.marked(lane)
    if m is None:
        return None
    return Gate(lanes.canonical(lane), 0.0, 0.0, 0, None, None, None, kind=DOWN, detail=incumbent_down.why(m))


def shut(conn, wanted, now: float | None = None) -> dict[str, Gate]:
    """lane -> its gate for each of `wanted` the gate closes now; a lane under an override is open, unless its incumbent is down."""
    out: dict[str, Gate] = {}
    for lane in dict.fromkeys(wanted):
        if not lane:
            continue
        dead = down_gate(lane)
        if dead is not None:
            out[dead.lane] = dead
            continue
        if override(conn, lane, now):
            continue
        got = gate_for(conn, lane)
        if got is not None:
            out[got.lane] = got
    return out


def keep(conn, rows: list[dict], lane_of=None, now: float | None = None, say=None) -> tuple[list[dict], dict[str, Gate]]:
    """`rows` less those in a closed lane, and the gates that closed them; each cut is a recorded limit."""
    from harness import cuts, lanes
    lane_of = lane_of or (lambda r: r.get("measure_lane") or r.get("lane") or "")
    shutting = shut(conn, [lanes.canonical(lane_of(r)) for r in rows], now)
    if not shutting:
        return rows, {}
    kept = [r for r in rows if lanes.canonical(lane_of(r)) not in shutting]
    for lane, g in shutting.items():
        n = sum(1 for r in rows if lanes.canonical(lane_of(r)) == lane)
        if g.kind != DOWN:
            cuts.cut("lane_gate_power", f"{lane}: {n} challenger(s) held back, power {g.power:.2f} at +{g.effect:.2f}",
                     value=GATE_POWER, kept=0, dropped=n, conn=conn)
        if say:
            say(f"  {g.why}")
    return kept, shutting


def hold_back(conn, name: str, lane: str, now: float | None = None) -> str:
    """'' when `lane` takes `name`; else why not, with the cut recorded and the name's paused runs there noted, still paused."""
    from harness import lanes, paused
    kept, gates = keep(conn, [{"name": name, "lane": lane}], now=now)
    if kept:
        return ""
    why = gates[lanes.canonical(lane)].why
    paused.note(conn, lanes.canonical(lane), name, why[:600])
    return why


def record(conn, rows: list[dict], gates: dict[str, Gate], lane_of=None) -> None:
    """Each held-back queued row keeps its place and says why: a queued verdict at the fetch tier naming the gate."""
    from harness import lanes, reasons
    from harness import memory_store as ms
    lane_of = lane_of or (lambda r: r.get("measure_lane") or r.get("lane") or "")
    for r in rows:
        g = gates.get(lanes.canonical(lane_of(r)))
        if g is not None:
            ms.decide_or_skip(conn, r["name"], "queued", tier=ms.FETCH, detail=g.why[:600],
                              reason=reasons.HARNESS if g.kind == DOWN else reasons.LIMIT, commit=False)
    conn.commit()


def status(conn, now: float | None = None) -> dict:
    """Every lane the gate closes, and the ones the owner has opened anyway, for the status page and `soh lane-gate`."""
    from harness import holdout, power
    now = time.time() if now is None else now
    closed, opened = [], []
    splits = holdout.splits()
    with power.prefetched(conn):
        gates = {lane: gate_for(conn, lane, splits[lane]) for lane in sorted(splits)}
    for lane, g in gates.items():
        if g is None:
            continue
        o = override(conn, lane, now)
        (opened if o else closed).append({**g.as_dict(), **({"until": o["until"], "said": o["said"]} if o else {})})
    from harness import incumbent_down
    down = [{"lane": k, "runner": v.get("runner", ""), "pair": v.get("pair", ""), "why": v.get("why", ""),
             "at": v.get("at", 0)} for k, v in sorted(incumbent_down.read().items()) if k != "?"]
    return {"threshold": GATE_POWER, "closed": closed, "opened": opened, "down": down, "issue": GROWTH_ISSUE}
