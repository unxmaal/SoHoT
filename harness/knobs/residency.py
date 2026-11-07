"""Knobs of `soh residency-sim`, the residency trace replay (#1559)."""
from harness.knobs.base import _k

R = "harness/residency.py"

KNOBS = [
    _k("residency_fallback_s_per_gb", [f"{R}:FALLBACK_S_PER_GB"], [0.5, 1.0, 2.0],
       note="load seconds per weights GB when no router log measured a load to fit from (#1559)"),
    _k("residency_window_s", [f"{R}:WINDOW_S"], [600.0, 3600.0, 86400.0],
       note="seconds back GreedyDual-Size counts a model's requests over for its keep-value (#1559)"),
]

NOT_GATING = {
    f"{R}:simulate->SimpleNamespace(seconds)": "a running total of load seconds, starting at zero (#1559)",
    f"{R}:simulate->SimpleNamespace(batch_seconds)": "a running total of batch load seconds, starting at zero (#1559)",
    f"{R}:simulate->SimpleNamespace(over_seconds)": "a running total of seconds over budget, starting at zero (#1559)",
}

NEVER_CUTS = {
    f"{R}:WINDOW_S": "a keep-value weight in a replay; every request is replayed (#1559)",
    f"{R}:FALLBACK_S_PER_GB": "an estimated load time, reported as the fallback; nothing is dropped (#1559)",
}
