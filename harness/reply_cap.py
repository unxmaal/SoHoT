"""The reply budget an eval asks a lane-model at: the least its stored runs show keeps its passes (#1352)."""
from __future__ import annotations

import json
import math

from harness import completion, convertible, reasons, yield_stop

#: The share of a model's passing replies, ranked by completion tokens, the cap must let finish. #1352.
QUANTILE = 0.95
#: Room above that reply's tokens, as a share of them. #1352.
MARGIN = 0.25
#: Passes a model (or a budget sweep's best budget) needs before its rows set a cap. #1352.
MIN_PASSES = 8
#: How far, in standard errors of the paired difference, a swept budget may fall short of the best and still count. #1352.
NOISE_Z = 1.96
#: The share of a model's stored seconds a cap must save before its runs ask at it. #1352.
MIN_SAVED = 0.1
#: A token-derived cap is a whole number of these, so a little new evidence does not move a run's budget.
STEP = 4096


def _receipt(raw) -> dict:
    try:
        return json.loads(raw or "{}") or {}
    except ValueError:
        return {}


def stored(conn, lane: str) -> list[dict]:
    """Every unflagged measured run in `lane` by the single-reply harness, one entry per candidate, rows that ran only."""
    from harness import power, reverify, runs
    flagged = reverify._flagged_runs(conn)
    sql = ("SELECT runs.id AS run_id, runs.receipt, COALESCE(c.spec, res.candidate) AS spec, res.case_id, "
           "res.repeat_index, res.passed, res.seconds, res.failure_class, res.hit_limit, res.metrics, res.attempts "
           "FROM results res JOIN runs ON res.run_id = runs.id LEFT JOIN candidates c ON c.id = res.candidate_id "
           "WHERE runs.lane = ? AND runs.tier = ? ORDER BY runs.id, res.seq")
    by: dict = {}
    for r in conn.execute(sql, (lane, runs.MEASURE)):
        if r["run_id"] in flagged:
            continue
        got = by.setdefault((r["run_id"], r["spec"]), {"run_id": r["run_id"], "spec": r["spec"],
                                                       "receipt": _receipt(r["receipt"]), "rows": []})
        got["rows"].append(dict(r))
    out = []
    for got in by.values():
        receipt = got["receipt"]
        if receipt.get("harness"):
            continue
        ran = [r for r in got["rows"] if (r["failure_class"] or "") not in reasons.NEVER_RAN]
        if not ran:
            continue
        budget, ladder = power.reply_settings(json.dumps(receipt), lane)
        out.append({"run_id": got["run_id"], "spec": got["spec"], "base": convertible.base_of(got["spec"]),
                    "budget": budget, "ladder": ladder, "top": convertible._top(receipt, got["rows"]) or budget,
                    "setting": convertible._setting(receipt, lane, got["spec"]), "rows": ran})
    return out


def _cases(run: dict) -> dict:
    return {(r["case_id"], r["repeat_index"]): bool(r["passed"]) for r in run["rows"]}


def within_noise(best: dict, other: dict, z: float | None = None) -> bool:
    """Whether `other` passes as many of the shared cases as `best` but for rerun noise: a paired sign test on the cases only one passes."""
    z = NOISE_Z if z is None else float(z)
    lost = sum(best[k] and not other[k] for k in best)
    gained = sum(other[k] and not best[k] for k in best)
    return lost - gained <= z * math.sqrt(lost + gained)


def sweep(runs: list[dict], min_passes: int | None = None, z: float | None = None) -> dict | None:
    """The smallest flat budget whose passes on the shared cases are within noise of the best budget's, per one setting;
    at each budget the run with the most rows, the newest of those."""
    least = MIN_PASSES if min_passes is None else int(min_passes)
    groups: dict = {}
    for r in runs:
        if not r["ladder"] and r["budget"]:
            at = groups.setdefault(r["setting"], {})
            held = at.get(r["budget"])
            if held is None or (len(r["rows"]), r["run_id"]) > (len(held["rows"]), held["run_id"]):
                at[r["budget"]] = r
    found = []
    for at in groups.values():
        if len(at) < 2:
            continue
        cases = {b: _cases(r) for b, r in at.items()}
        shared = set.intersection(*(set(c) for c in cases.values()))
        if not shared:
            continue
        on = {b: {k: c[k] for k in shared} for b, c in cases.items()}
        passes = {b: sum(c.values()) for b, c in on.items()}
        best = min(sorted(passes), key=lambda b: -passes[b])
        if passes[best] < least:
            continue
        cap = min(b for b in passes if within_noise(on[best], on[b], z))
        secs = {b: sum(float(row["seconds"] or 0.0) for row in at[b]["rows"]
                       if (row["case_id"], row["repeat_index"]) in shared) for b in at}
        top = max(at)
        found.append({"cap": cap, "from": "sweep", "best": best, "cases": len(shared),
                      "saved_share": round(1 - secs[cap] / secs[top], 4) if secs[top] else 0.0,
                      "passes": {str(b): passes[b] for b in sorted(passes)},
                      "runs": {str(b): at[b]["run_id"] for b in sorted(at)}})
    return max(found, key=lambda f: f["cases"]) if found else None


def stepped(tokens: float, budget: int) -> int:
    """`tokens` rounded up to a whole STEP, never over the lane's budget."""
    return min(int(budget), int(math.ceil(tokens / STEP)) * STEP)


def by_tokens(runs: list[dict], lane: str, quantile: float | None = None, margin: float | None = None,
              min_passes: int | None = None) -> dict | None:
    """The quantile of passing replies' completion tokens plus margin, from runs that gave the lane's whole budget."""
    q = QUANTILE if quantile is None else float(quantile)
    m = MARGIN if margin is None else float(margin)
    least = MIN_PASSES if min_passes is None else int(min_passes)
    budget = completion.budget(lane)
    full = [r for r in runs if r["top"] >= budget]
    tokens = sorted(n for r in full for row in r["rows"] if row["passed"]
                    and (n := yield_stop.tokens_of(row)) is not None)
    if len(tokens) < max(1, least):
        return None
    at = tokens[max(0, math.ceil(q * len(tokens)) - 1)]
    cap = stepped(at * (1 + m), budget)
    saved = yield_stop.rescore([row for r in full for row in r["rows"]], cap if cap < budget else None)["saved_share"]
    return {"cap": cap, "from": "tokens", "passes": len(tokens), "quantile": q, "margin": m, "tokens": at,
            "most": tokens[-1], "saved_share": saved, "runs": sorted({r["run_id"] for r in full})}


def derive(conn, lane: str, found: list[dict] | None = None) -> dict:
    """{lane, budget, models}: each base model's cap in `lane`, from its own runs only."""
    budget = completion.budget(lane)
    found = stored(conn, lane) if found is None else found
    models: dict = {}
    for r in found:
        models.setdefault(r["base"], []).append(r)
    out = {base: sweep(rs) or by_tokens(rs, lane) for base, rs in sorted(models.items())}
    return {"lane": lane, "budget": budget, "models": {b: got for b, got in out.items() if got}}


def entry(derived: dict, spec: str, min_saved: float | None = None) -> dict:
    """The cap a run of `spec` asks at: its model's, else the lane's budget, so a model's first exam is its evidence;
    a cap saving under MIN_SAVED of its stored seconds is not worth a receipt no older run compares with."""
    least = MIN_SAVED if min_saved is None else float(min_saved)
    base = convertible.base_of(spec)
    got = derived["models"].get(base)
    if not got:
        return {"cap": derived["budget"], "from": "budget", "model": base}
    if int(got["cap"]) >= derived["budget"] or got["saved_share"] < least:
        return {"cap": derived["budget"], "from": "budget", "model": base, "derived": got}
    return {**got, "model": base}


def cap_for(conn, lane: str, specs) -> tuple[int, dict]:
    """(the budget a run of `specs` asks at, spec -> its cap): the largest cap among them, so a paired run shares one budget."""
    budget = completion.budget(lane)
    specs = [s for s in specs if s]
    if not budget or not specs:
        return budget, {}
    derived = derive(conn, lane)
    caps = {s: entry(derived, s) for s in specs}
    return max(int(c["cap"]) for c in caps.values()), caps


def budget_for(lane: str, specs) -> tuple[int, dict]:
    """cap_for on this home's store; the lane's budget where the store cannot be read."""
    from harness import memory_store as ms
    try:
        conn = ms.connect()
        try:
            return cap_for(conn, lane, specs)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - no stored evidence means the lane's budget
        return completion.budget(lane), {}


def said(e: dict) -> str:
    """One line on where a cap came from."""
    if e["from"] == "budget" and e.get("derived"):
        d = e["derived"]
        why = "is the budget" if d["cap"] >= e["cap"] else f"would save {d['saved_share']:.0%}, under {MIN_SAVED:g}"
        return f"{e['cap']}, the lane's budget: its derived {d['cap']} {why} ({said(d)})"
    if e["from"] == "budget":
        return f"{e['cap']}, the lane's budget: under {MIN_PASSES} passes of its own at it"
    if e["from"] == "sweep":
        passes = ", ".join(f"{b}: {n}" for b, n in e["passes"].items())
        return (f"{e['cap']} from its budget sweep on {e['cases']} shared cases ({passes} passed; "
                f"best {e['best']}, runs {', '.join(str(v) for v in e['runs'].values())})")
    return (f"{e['cap']} from its {e['passes']} passes: the {e['quantile']:g} quantile used {e['tokens']} tokens "
            f"(most {e['most']}), plus {e['margin']:g}")


def backtest(lane: str, cap: int, base: str, found: list[dict]) -> dict:
    """What `cap` would have kept, lost and saved on `base`'s stored rows at the lane's whole budget."""
    budget = completion.budget(lane)
    rows = [row for r in found if r["base"] == base and r["top"] >= budget for row in r["rows"]]
    got = yield_stop.rescore(rows, cap if cap < budget else None)
    return {k: got[k] for k in ("kept", "lost", "stopped", "seconds", "saved_s", "saved_share")}


def report(conn, lanes=None) -> list[dict]:
    """Each text lane-model's cap, with what it would have kept, lost and saved on that model's stored rows."""
    out = []
    for lane in lanes or sorted(completion.BUDGET):
        if not completion.budget(lane):
            continue
        found = stored(conn, lane)
        derived = derive(conn, lane, found)
        for base in sorted({r["base"] for r in found}):
            e = entry(derived, base)
            out.append({"lane": lane, "budget": derived["budget"], **e, **backtest(lane, e["cap"], base, found)})
    return out
