"""The lane gate: a lane whose power plan at its adopt effect is below lane_gate_power takes no challengers; the owner's recorded, expiring override (#2164)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

#: A lane whose plan power at its adopt effect is under this is closed to challengers. #2164.
GATE_POWER = 0.8
#: How long the owner's "open anyway" lasts before the lane closes again. #2164.
OPEN_S = 3 * 86400.0
#: The holds row kind of an override, then the lane.
OPEN_KIND = "lane-open:"
GROWTH_ISSUE = "https://github.com/unxmaal/SoHoT/issues/603"
OWNER = "owner: from the status page"


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


@dataclass(frozen=True)
class Gate:
    lane: str
    power: float
    effect: float
    holdout: int
    cases_needed: int | None
    more_holdout: int | None
    more_cases: int | None

    @property
    def why(self) -> str:
        need = ("no holdout size reaches it" if self.cases_needed is None else
                f"needs {self.more_holdout} more holdout cases ({self.cases_needed} in all, {self.holdout} here)")
        return (f"{self.lane} lane closed to challengers: power {self.power:.2f} at +{self.effect:.2f} is under "
                f"lane_gate_power {GATE_POWER:.2f}, {need}; soh lane-gate open {self.lane} overrides for a while")

    def as_dict(self) -> dict:
        return {"lane": self.lane, "power": round(self.power, 4), "effect": self.effect, "holdout": self.holdout,
                "cases_needed": self.cases_needed, "more_holdout": self.more_holdout, "more_cases": self.more_cases,
                "why": self.why, "issue": GROWTH_ISSUE}


def _row(r: dict) -> dict:
    return {"candidate": r.get("candidate"), "case_id": r.get("case_id"),
            "passed": r.get("passed"), "seconds": r.get("seconds"), "metrics": r.get("metrics")}


def profile(lane: str, receipts: dict, conn) -> tuple[str, str, dict, float | None, tuple, list]:
    """(incumbent key, its spec, its draws per case, its median seconds here at the lane's budget, settings, machines)."""
    from harness import adopt, candidates, power, reply_cap, runs, screen, winners
    served = adopt.default_for(lane, winners.typed().get(lane, ""))
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
        draws, _ = power.draws_from([r for rows in sets for r in rows], key, lane)
        timed = [_row(r) for got in receipts[lane] if power.receipt_here(got["environment"])
                 and power.reply_settings(json.dumps(got["receipt"]), lane) == settings for r in got["rows"]]
        return key, spec or served, draws, power.draws_from(timed, key)[1], settings, machines
    key = key or spec
    draws, median = (power.served_profile(conn, lane, spec, settings, machines)
                     if spec else ({}, None))
    return key, spec or served, draws, median, settings, machines


def calc(conn, lane: str, split, receipts: dict | None = None, effect: float | None = None) -> Calc:
    """The power plan over the lane's holdout at the incumbent's measured rates; `soh adopt --power` and the gate share it."""
    from evals.run import STOCHASTIC_MODALITIES
    from harness import adopt, power
    receipts = receipts or {}
    key, inc_spec, draws, inc_s, settings, machines = profile(lane, receipts, conn)
    rates, seen = power.rates_from(draws, split.holdout)
    rho = power.icc([list(draws.values())])
    effect = effect or power.effect_for(lane)
    tested = adopt.comparisons(conn, lane, split.version)
    alpha = adopt.alpha_for(tested)
    plan = power.plan([rates[c] for c in split.holdout], effect, stochastic=lane in STOCHASTIC_MODALITIES,
                      observed=seen, rho=rho, alpha=alpha, unmeasured=not any(draws.values()))
    return Calc(key, inc_spec, draws, inc_s, settings, machines, rates, seen, effect, tested, alpha, plan)


def closes(plan, threshold: float | None = None) -> bool:
    """Whether a plan closes its lane: measured rates, and power under the gate. An unmeasured plan is a guess and never closes."""
    return not plan.unmeasured and plan.power < (GATE_POWER if threshold is None else threshold)


def gate_for(conn, lane: str) -> Gate | None:
    """The gate on one lane from its power plan, whatever the owner's override says; None when it is open by power."""
    import math

    from harness import holdout, lanes
    lane = lanes.canonical(lane)
    split = holdout.for_lane(lane)
    if not (split.dev or split.holdout):
        return None
    c = calc(conn, lane, split)
    if not closes(c.plan):
        return None
    need = c.plan.cases_needed
    more = max(0, need - len(split.holdout)) if need else None
    return Gate(lane, c.plan.power, c.effect, len(split.holdout), need, more,
                None if more is None else math.ceil(more / holdout.FRACTION))


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


def shut(conn, wanted, now: float | None = None) -> dict[str, Gate]:
    """lane -> its gate for each of `wanted` the gate closes now; a lane under an override is open."""
    out: dict[str, Gate] = {}
    for lane in dict.fromkeys(wanted):
        if not lane or override(conn, lane, now):
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
            ms.decide_or_skip(conn, r["name"], "queued", tier=ms.FETCH, detail=g.why[:600], reason=reasons.LIMIT,
                              commit=False)
    conn.commit()


def status(conn, now: float | None = None) -> dict:
    """Every lane the gate closes, and the ones the owner has opened anyway, for the status page and `soh lane-gate`."""
    from harness import holdout
    now = time.time() if now is None else now
    closed, opened = [], []
    for lane in sorted(holdout.splits()):
        g = gate_for(conn, lane)
        if g is None:
            continue
        o = override(conn, lane, now)
        (opened if o else closed).append({**g.as_dict(), **({"until": o["until"], "said": o["said"]} if o else {})})
    return {"threshold": GATE_POWER, "closed": closed, "opened": opened, "issue": GROWTH_ISSUE}
