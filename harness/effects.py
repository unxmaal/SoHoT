"""Each lane's smallest adopted-for gain, from the share of cells a same-config rerun flips each way. #725."""
from __future__ import annotations

import json
import math
from collections import defaultdict

#: The smallest per-cell gain worth a model switch on a lane whose reruns never flip.
FLOOR = 0.05
#: Cases measured twice under one config before a lane's churn sets its effect.
MIN_CASES = 30


def config(receipt: str, key: str, lane: str, machine) -> str:
    """What a same-config rerun holds fixed for one receipt key: machine, reply budget, sampling, knobs, serving."""
    from harness import power
    try:
        got = json.loads(receipt or "{}")
    except ValueError:
        got = {}
    return json.dumps([lane, key, machine, power.reply_settings(receipt, lane),
                       (got.get("requests") or {}).get(key), (got.get("server_sampling") or {}).get(key),
                       got.get("knobs"), (got.get("served") or {}).get(key)], sort_keys=True, default=str)


def _draws(conn) -> dict:
    """lane -> config -> base case -> the lane-metric draws of its measure rows. #1082."""
    from harness import holdout, power, reasons
    out: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in conn.execute("SELECT u.lane, u.machine_id, u.receipt, x.candidate, x.case_id, x.passed, x.metrics, "
                          "x.failure_class FROM results x JOIN runs u ON u.id = x.run_id WHERE u.tier = 'measure'"):
        if (r["failure_class"] or "") in reasons.NEVER_RAN or not r["lane"]:
            continue
        row = {"passed": r["passed"], "metrics": r["metrics"]}
        out[r["lane"]][config(r["receipt"], r["candidate"], r["lane"], r["machine_id"])][
            holdout.base_id(r["case_id"])].append(power.draw(row, r["lane"]))
    return out


def churn(conn) -> dict[str, dict]:
    """lane -> the pooled within-case variance of same-config draws (the share flipped each way), the cases and configs behind it."""
    out = {}
    for lane, configs in _draws(conn).items():
        num = den = 0.0
        cases, used = 0, set()
        for cfg, by_case in configs.items():
            for draws in by_case.values():
                if len(draws) < 2:
                    continue
                mean = sum(draws) / len(draws)
                num += sum((d - mean) ** 2 for d in draws)
                den += len(draws) - 1
                cases += 1
                used.add(cfg)
        out[lane] = {"churn": num / den if den else None, "cases": cases, "configs": len(used)}
    return out


def effect_of(basis: dict) -> float | None:
    """The churn rounded up to 0.01 and never under FLOOR; None when fewer than MIN_CASES back it."""
    if basis.get("churn") is None or int(basis.get("cases") or 0) < MIN_CASES:
        return None
    return max(FLOOR, math.ceil(round(float(basis["churn"]) * 100, 6)) / 100)


def derive(conn, record: bool = True) -> dict[str, dict]:
    """lane -> its churn basis and the effect it gives (None: the lane keeps power.DEFAULT_EFFECT); `record` notes the floor's cut."""
    from harness import cuts
    out = {lane: {**basis, "effect": effect_of(basis)} for lane, basis in sorted(churn(conn).items())}
    floored = [f"{lane} {d['churn']:.4f}" for lane, d in out.items()
               if d["effect"] == FLOOR and d["churn"] is not None and d["churn"] < FLOOR]
    if floored and record:
        cuts.cut("adopt_effect_floor", f"rerun churn under the floor, raised to +{FLOOR:g}: {', '.join(floored)}",
                 kept=len(out) - len(floored), dropped=len(floored))
    return out


def _lane(detail: str, fallback: str) -> str:
    from harness import lanes
    head = (detail or "").split(":", 1)[0].strip().lower()
    return head if head in lanes.ALL else (fallback or "")


def _plan(raw: str) -> dict:
    try:
        got = json.loads(raw or "{}")
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _stored(row, plan: dict) -> str:
    from harness import reasons
    if row["outcome"] == "measured":
        return "adopted"
    return row["failure_class"] or (reasons.CANDIDATE if row["outcome"] == "declined" else row["outcome"])


def _replayed(row, plan: dict, stored: str, effect: float, how: str) -> tuple[str, str]:
    """(class, why) the verdict would have under `effect` and the #725 confirmation."""
    from harness import reasons
    detail = row["detail"] or ""
    old = float(plan.get("effect") or effect)
    if stored == "adopted":
        dev = plan.get("dev") or {}
        if how == "by-hand" or "taken from measurement" in detail:
            return stored, "not decided by the paired gate"
        if dev.get("p") is not None and int(dev.get("gained") or 0) > int(dev.get("lost") or 0) \
                and float(dev["p"]) <= _alpha():
            return stored, f"its run's dev cells confirm it (p={float(dev['p']):.3f})"
        return reasons.CONFIRMING, "a gate win with no dev confirmation waits for a night confirmation run"
    if stored in (reasons.INCONCLUSIVE,) or not plan:
        return stored, "no power plan, or nothing decided"
    if stored == reasons.LANE_TOO_SMALL:
        return (stored, "a smaller effect needs more cases") if effect <= old + 1e-9 else (
            stored, f"may change: +{effect:.2f} needs fewer cases than +{old:.2f}")
    if "futility" in detail:
        return (stored, "conditional power only falls at a smaller effect") if effect <= old + 1e-9 else (
            stored, f"may change: conditional power rises at +{effect:.2f}")
    if "significantly worse" in detail:
        return stored, "a significant loss does not depend on the effect"
    if plan.get("unmeasured"):
        return reasons.UNDERPOWERED, "the plan rests on assumed rates"
    mde = plan.get("mde")
    if mde is None:
        mde = row["mde"]
    if mde is None:
        return stored, "no minimum detectable effect stored or computable from its run"
    if float(mde) <= effect + 1e-9:
        return reasons.CANDIDATE, f"its run could see +{float(mde):.2f}, within the lane's +{effect:.2f}"
    return reasons.UNDERPOWERED, f"its run could see only +{float(mde):.2f}, above the lane's +{effect:.2f}"


def _run_mde(conn, vid: int, lane: str, plan: dict) -> float | None:
    """The MDE of a verdict that stored none, from its run's incumbent draws on the lane's holdout at the plan's repeat, rho and alpha."""
    from harness import holdout, power
    got = conn.execute("SELECT v.run_id, c.receipt_key FROM verdicts v LEFT JOIN candidates c ON c.id = v.candidate_id "
                       "WHERE v.id = ?", (vid,)).fetchone()
    if got is None or got["run_id"] is None:
        return None
    rows = [dict(r) for r in conn.execute("SELECT candidate, case_id, passed, seconds, metrics FROM results WHERE run_id = ?",
                                          (got["run_id"],))]
    others = sorted({r["candidate"] for r in rows} - {got["receipt_key"]})
    if len(others) != 1:
        return None
    try:
        cases = holdout.for_lane(lane).holdout
    except Exception:  # noqa: BLE001
        return None
    draws, _ = power.draws_from(rows, others[0], lane)
    rates = [sum(draws[c]) / len(draws[c]) for c in cases if draws.get(c)]
    if not rates:
        return None
    return power.mde(rates, int(plan.get("repeat") or 1), float(plan.get("alpha") or _alpha()),
                     float(plan.get("rho") if plan.get("rho") is not None else power.DEFAULT_RHO),
                     float(plan.get("target") or power.TARGET))


def _alpha() -> float:
    from harness import adopt
    return adopt.ALPHA


def replay(conn, effects: dict) -> list[dict]:
    """Every stored adopt verdict's class as stored and under `effects` (lane -> effect) with the confirmation step."""
    from harness import power
    rows = conn.execute(
        "SELECT v.id, v.outcome, v.failure_class, v.detail, v.power, c.lane AS cand_lane, a.how "
        "FROM verdicts v LEFT JOIN candidates c ON c.id = v.candidate_id "
        "LEFT JOIN adoptions a ON a.verdict_id = v.id WHERE v.tier = 'adopt' ORDER BY v.id").fetchall()
    out = []
    for r in rows:
        lane = _lane(r["detail"], r["cand_lane"])
        plan = _plan(r["power"])
        stored = _stored(r, plan)
        effect = float(effects.get(lane, power.DEFAULT_EFFECT))
        r = {**dict(r), "mde": None if plan.get("mde") is not None or stored != "candidate" or not plan
             else _run_mde(conn, r["id"], lane, plan)}
        replayed, why = _replayed(r, plan, stored, effect, r["how"] or "")
        out.append({"id": r["id"], "lane": lane, "stored": stored, "replayed": replayed, "effect": effect,
                    "why": why, "detail": (r["detail"] or "")[:120]})
    return out
