"""Model residency by trace replay: LRU, pinned+LRU, GreedyDual-Size and Belady's offline bound over one demand trace (#1559)."""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from types import SimpleNamespace
from typing import NamedTuple

#: Seconds back from a request that GreedyDual-Size counts the model's requests over for its keep-value.
WINDOW_S = 3600.0
#: Load seconds per weights GB when no model's load was measured to fit a rate from.
FALLBACK_S_PER_GB = 1.0

LRU, PINNED, GDS, BELADY = "lru", "pinned-lru", "gds", "belady"
POLICIES = (LRU, PINNED, GDS, BELADY)
INTERACTIVE, BATCH, JOB = "interactive", "batch", "job"


class Req(NamedTuple):
    start: float
    end: float
    model: str
    kind: str = INTERACTIVE


@dataclass
class _Held:
    ready: float
    busy: float
    last: float
    value: float = 0.0


def rank(values: list[float], q: float) -> float | None:
    """The nearest-rank q quantile, None for no values."""
    v = sorted(values)
    return v[max(math.ceil(q * len(v)) - 1, 0)] if v else None


def _victim(policy: str, held: dict, cands: list[str], t: float, starts: dict) -> str:
    if policy == GDS:
        return min(cands, key=lambda m: (held[m].value, held[m].last, m))
    if policy == BELADY:
        def nxt(m):
            s = starts[m]
            i = bisect.bisect_right(s, t)
            return s[i] if i < len(s) else math.inf
        return max(cands, key=lambda m: (nxt(m), -held[m].last, m))
    return min(cands, key=lambda m: (held[m].last, m))


def simulate(reqs, sizes: dict, loads: dict, budget_gb: float, policy: str, pins=(),
             window_s: float | None = None) -> dict:
    """Replay `reqs` against one policy: a missing model loads (evicting idle models the policy picks), callers wait the load."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}; one of {', '.join(POLICIES)}")
    window = WINDOW_S if window_s is None else float(window_s)
    pinned = frozenset(pins) if policy == PINNED else frozenset()
    reqs = sorted(reqs, key=lambda r: (r.start, r.end, r.model))
    starts: dict[str, list[float]] = {}
    for r in reqs:
        starts.setdefault(r.model, []).append(r.start)
    held: dict[str, _Held] = {}
    used, floor, last_t = 0.0, 0.0, None
    k = SimpleNamespace(requests=0, hits=0, loads=0, seconds=0.0, evictions=0, waits=[], batch_loads=0,
                        batch_seconds=0.0, cases=0, over_moments=0, over_seconds=0.0, peak_gb=0.0)
    for r in reqs:
        t, m = r.start, r.model
        if last_t is not None and used > budget_gb:
            k.over_seconds += t - last_t
        last_t = t
        h = held.get(m)
        loaded = h is None
        if loaded:
            while used + sizes[m] > budget_gb:
                cands = [x for x in held if held[x].busy <= t and x not in pinned]
                if not cands:
                    break
                v = _victim(policy, held, cands, t, starts)
                floor = held[v].value if policy == GDS else floor
                used -= sizes[v]
                del held[v]
                k.evictions += 1
            used += sizes[m]
            if used > budget_gb:
                k.over_moments += 1
                k.peak_gb = max(k.peak_gb, used)
            h = held[m] = _Held(ready=t + loads[m], busy=t, last=t)
            k.loads += 1
            k.seconds += loads[m]
            if r.kind != INTERACTIVE:
                k.batch_loads += 1
                k.batch_seconds += loads[m]
        wait = max(h.ready - t, 0.0)
        h.busy = max(h.busy, t + wait + (r.end - r.start))
        h.last = t
        if policy == GDS:
            s = starts.get(m, [])
            freq = max(bisect.bisect_right(s, t) - bisect.bisect_right(s, t - window), 1)
            h.value = floor + freq * loads[m] / max(sizes[m], 1e-9)
        if r.kind == JOB:
            continue
        k.requests += 1
        k.hits += not loaded and wait == 0
        if r.kind == INTERACTIVE:
            k.waits.append(wait)
        else:
            k.cases += 1
    if held and last_t is not None and used > budget_gb:
        k.over_seconds += max(max(h.busy for h in held.values()) - last_t, 0.0)
    return {
        "policy": policy, "requests": k.requests, "hits": k.hits,
        "hit_rate": round(k.hits / k.requests, 4) if k.requests else None,
        "loads": k.loads, "load_s": round(k.seconds, 3), "evictions": k.evictions,
        "interactive": {"n": len(k.waits), "p50_s": rank(k.waits, 0.5), "p95_s": rank(k.waits, 0.95),
                        "max_s": max(k.waits) if k.waits else None},
        "batch": {"cases": k.cases, "loads": k.batch_loads, "load_s": round(k.batch_seconds, 3),
                  "load_s_per_case": round(k.batch_seconds / k.cases, 4) if k.cases else None},
        "over_budget": {"moments": k.over_moments, "seconds": round(k.over_seconds, 3), "peak_gb": round(k.peak_gb, 3)},
    }


def compare(reqs, sizes: dict, loads: dict, budget_gb: float, pins=(), window_s: float | None = None) -> dict:
    """Every policy over the same trace."""
    reqs = list(reqs)
    return {p: simulate(reqs, sizes, loads, budget_gb, p, pins, window_s) for p in POLICIES}


def fit_rate(measured: dict, weights_gb: dict) -> dict:
    """Load seconds per weights GB through the origin over measured models, with its leave-one-out error."""
    pts = [(weights_gb[m], s) for m, s in measured.items() if weights_gb.get(m)]
    if not pts:
        return {"s_per_gb": FALLBACK_S_PER_GB, "models": 0, "error_s": None, "fallback": True}

    def rate(ps):
        return sum(g * s for g, s in ps) / sum(g * g for g, _ in ps)

    errs = [abs(rate(pts[:i] + pts[i + 1:]) * g - s) for i, (g, s) in enumerate(pts)] if len(pts) > 1 else []
    return {"s_per_gb": round(rate(pts), 4), "models": len(pts),
            "error_s": round(rank(errs, 0.5), 2) if errs else None, "fallback": False}
