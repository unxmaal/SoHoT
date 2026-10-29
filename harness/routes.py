"""Request-routing trial arms per lane: LiteLLM complexity routers over the lane alias and the cloud alias, the adaptive one fed our verdicts. #1338."""
from __future__ import annotations

import threading
from collections import OrderedDict

from harness import methods

#: The free-text lanes the text runner grades with no response_format schema, so the cloud alias can answer them too.
LANES = methods.TEXT_LANES
CLOUD = "cloud-opus"
HEURISTIC, ADAPTIVE = "auto", "adaptive"
ARMS = (HEURISTIC, ADAPTIVE)
ALIAS = "sohot-{lane}-{arm}"
ARM_KEY, LANE_KEY = "route_arm", "route_lane"
ROUTER_MODEL = "auto_router/complexity_router"
LOCAL_TIERS = ("SIMPLE", "MEDIUM")
CLOUD_TIERS = ("COMPLEX", "REASONING")
#: Weight of the sampled pass rate against cost in the adaptive pick (LiteLLM's own default is 0.7).
QUALITY_WEIGHT = 0.9
#: Score an adaptive pick loses per tier step from the classified tier; LiteLLM's 0.5 lets no verdict cross a tier.
TIER_PENALTY = 0.05
#: Request header carrying verdicts on earlier calls: "call_id=pass,call_id=fail".
HEADER = "x-sohot-route-feedback"
#: Reply header naming the tier model a router arm sent the request to.
ROUTED_HEADER = "x-sohot-routed"
PASS, FAIL = "pass", "fail"
#: Calls an adaptive arm routed that the gateway keeps while their verdict is out.
REMEMBERED_CALLS = 4096
#: Seconds between the gateway's reads of closed delegation outcomes for the calls it keeps.
DELEGATION_POLL_S = 60.0


def alias(lane: str, arm: str) -> str:
    return ALIAS.format(lane=lane, arm=arm)


def entry(lane: str, arm: str, local: str, cloud: str = CLOUD) -> dict:
    """One arm's gateway config entry: SIMPLE and MEDIUM to `local`, COMPLEX and REASONING to `cloud`."""
    if arm not in ARMS:
        raise ValueError(f"no routing arm {arm!r}; arms are {', '.join(ARMS)}")
    cfg = {"tiers": {**{t: local for t in LOCAL_TIERS}, **{t: cloud for t in CLOUD_TIERS}},
           "classifier_type": "heuristic"}
    if arm == ADAPTIVE:
        cfg.update(adaptive=True, adaptive_eligible="all", tier_distance_penalty=TIER_PENALTY,
                   adaptive_weights={"quality": QUALITY_WEIGHT, "cost": round(1.0 - QUALITY_WEIGHT, 6)})
    return {"model_name": alias(lane, arm), ARM_KEY: arm, LANE_KEY: lane,
            "litellm_params": {"model": ROUTER_MODEL, "complexity_router_config": cfg}}


def entries(lanes_served: dict, names: set, cloud: str = CLOUD) -> list[dict]:
    """Both arms for each LANES lane the served config names (lane -> its alias), when it also names `cloud`."""
    if cloud.lower() not in names:
        return []
    return [entry(lane, arm, lanes_served[lane], cloud)
            for lane in LANES if lane in lanes_served for arm in ARMS]


def is_cloud(routed: str) -> bool:
    """Whether a routed tier model is the cloud: the arms' cloud tier, or any hosted entry."""
    from harness import models
    return routed == CLOUD or models.hosted(routed)


def is_router(e: dict) -> bool:
    return str(((e or {}).get("litellm_params") or {}).get("model") or "").startswith("auto_router/")


#: Failures that are the answer's own, so a verdict on the routed model; a harness or limit failure says nothing.
ANSWER_FAILURES = frozenset({"content_failed", "token_budget_exhausted", "degenerate", "runaway", "blank_output"})


def verdict(passed: bool, failure_class: str = "") -> str:
    """PASS, FAIL, or "" when the row says nothing about the model that answered."""
    if passed:
        return PASS
    return FAIL if failure_class in ANSWER_FAILURES else ""


_PENDING: list[tuple[str, str]] = []
_LOCK = threading.Lock()


def report(call_id: str, got: str) -> None:
    """Queue a verdict on a call; the next gateway request carries it."""
    if call_id and got in (PASS, FAIL):
        with _LOCK:
            _PENDING.append((call_id, got))


def headers() -> dict:
    """The feedback header for the next request, emptying the queue; {} with nothing queued."""
    with _LOCK:
        if not _PENDING:
            return {}
        out = ",".join(f"{c}={v}" for c, v in _PENDING)
        _PENDING.clear()
    return {HEADER: out}


def parse(value: str) -> list[tuple[str, str]]:
    got = []
    for part in str(value or "").split(","):
        call_id, _, v = part.strip().partition("=")
        if call_id and len(call_id) <= 128 and v in (PASS, FAIL):
            got.append((call_id, v))
    return got


def delta(got: str) -> tuple[float, float]:
    """(alpha, beta) added to the routed model's cell."""
    return (1.0, 0.0) if got == PASS else (0.0, 1.0)


class Feed:
    """Calls an adaptive arm routed, by call id, until a verdict arrives. #1338."""

    def __init__(self, cap: int = REMEMBERED_CALLS):
        self.cap = cap
        self.calls: OrderedDict[str, tuple[str, str, str]] = OrderedDict()
        self.applied = 0

    def remember(self, call_id: str, router: str, request_type: str, model: str) -> None:
        if not (call_id and router and model):
            return
        self.calls[call_id] = (router, request_type or "general", model)
        self.calls.move_to_end(call_id)
        dropped = 0
        while len(self.calls) > self.cap:
            self.calls.popitem(last=False)
            dropped += 1
        if dropped:
            from harness import cuts
            cuts.cut("route_remembered_calls", "adaptive-arm calls awaiting a verdict", value=self.cap,
                     kept=len(self.calls), dropped=dropped)

    def take(self, call_id: str):
        return self.calls.pop(call_id, None)

    def waiting(self) -> list[str]:
        return list(self.calls)


def closed(conn, ids: list[str]) -> list[tuple[str, str]]:
    """(call id, PASS or FAIL) for each of `ids` whose delegation outcome is closed accepted or rejected."""
    from harness import delegations
    if not ids:
        return []
    got = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for call_id, outcome in conn.execute(
                f"SELECT call_id, outcome FROM delegations WHERE outcome IS NOT NULL AND call_id IN "
                f"({','.join('?' * len(chunk))})", chunk):
            kind = delegations.kind(outcome)
            if kind in (delegations.ACCEPTED, delegations.REJECTED):
                got.append((call_id, PASS if kind == delegations.ACCEPTED else FAIL))
    return got


def arms_of(lane: str) -> list[str]:
    """The trial's candidates on a lane: the lane alias as it routes today, then each arm."""
    from harness import gateway
    return [gateway.LANE_ALIAS.format(lane)] + [alias(lane, a) for a in ARMS]


def run_rows(conn, run_id: int) -> list[dict]:
    import json
    return [{"candidate": c, "case": (case, rep), "passed": bool(p), "failure_class": fc or "",
             "seconds": float(s or 0.0), "metrics": json.loads(m or "{}")}
            for c, case, rep, p, fc, s, m in conn.execute(
                "SELECT candidate, case_id, repeat_index, passed, failure_class, seconds, metrics "
                "FROM results WHERE run_id = ? ORDER BY seq", (run_id,))]


def latest_run(conn, lane: str) -> int | None:
    got = conn.execute("SELECT r.id FROM runs r JOIN results x ON x.run_id = r.id WHERE r.lane = ? "
                       "AND x.candidate = ? ORDER BY r.id DESC LIMIT 1", (lane, alias(lane, ADAPTIVE))).fetchone()
    return got[0] if got else None


#: Failure classes that are a reply cut at our budget, counted apart since a cut is not a wrong answer (arXiv 2605.07395).
CUT = frozenset({"token_budget_exhausted", "context_exceeded"})


def arm_stats(rows: list[dict], candidate: str) -> dict:
    from harness import paired
    mine = [r for r in rows if r["candidate"] == candidate]
    judged = [r for r in mine if r["passed"] or r["failure_class"] not in paired.UNJUDGED]
    passed = sum(r["passed"] for r in judged)
    return {"candidate": candidate, "rows": len(mine), "judged": len(judged), "passed": passed,
            "rate": passed / len(judged) if judged else None,
            "cut": sum(r["failure_class"] in CUT for r in mine),
            "cloud_calls": sum(int(r["metrics"].get("routed_cloud") or 0) for r in mine),
            "cloud_tokens": sum(int(r["metrics"].get("cloud_tokens") or 0) for r in mine),
            "wall_s": round(sum(r["seconds"] for r in mine), 1)}


def versus(rows: list[dict], base: str, challenger: str, effect: float, alpha: float) -> dict:
    """#1338's adoption rule for `challenger` against `base`, paired on case and repeat."""
    from harness import paired
    a = {r["case"]: paired._verdict(r) for r in rows if r["candidate"] == base}
    b = {r["case"]: paired._verdict(r) for r in rows if r["candidate"] == challenger}
    shared = [k for k in a.keys() & b.keys() if a[k] is not None and b[k] is not None]
    lost = sum(a[k] > b[k] for k in shared)
    gained = sum(b[k] > a[k] for k in shared)
    p = paired.sign_test(min(lost, gained), lost + gained)
    sa, sb = arm_stats(rows, base), arm_stats(rows, challenger)
    drop = (sum(a[k] for k in shared) - sum(b[k] for k in shared)) / len(shared) if shared else 0.0
    better = gained > lost and p <= alpha and sb["cloud_tokens"] <= sa["cloud_tokens"]
    cheaper = sb["cloud_tokens"] < sa["cloud_tokens"] and drop <= effect
    why = ("passes more at equal or fewer cloud tokens" if better else
           "spends fewer cloud tokens within the lane's adopt effect" if cheaper else
           "neither passes more at no extra cloud tokens nor saves cloud tokens within the effect")
    return {"base": base, "challenger": challenger, "paired": len(shared), "lost": lost, "gained": gained,
            "p": p, "drop": drop, "effect": effect, "adopt": better or cheaper, "why": why}


def trial(conn, run_id: int, lane: str) -> dict:
    """Every candidate's arm stats in a stored run, and the adaptive arm judged against each other one."""
    from harness import adopt, power
    rows = run_rows(conn, run_id)
    split = (conn.execute("SELECT split FROM runs WHERE id = ?", (run_id,)).fetchone() or [""])[0]
    present = list(dict.fromkeys(r["candidate"] for r in rows))
    order = [c for c in arms_of(lane) if c in present] + [c for c in present if c not in arms_of(lane)]
    challenger = alias(lane, ADAPTIVE)
    effect = power.effect_for(lane)
    return {"run": run_id, "lane": lane, "split": split or "all", "arms": [arm_stats(rows, c) for c in order],
            "verdicts": [versus(rows, c, challenger, effect, adopt.ALPHA) for c in order if c != challenger]
            if challenger in present else []}
