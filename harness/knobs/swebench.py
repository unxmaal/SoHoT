"""Knobs of the SWE-bench Verified calibration (#922)."""
from harness.knobs.base import _k

KNOBS = [
    _k("swebench_alpha", ["evals/swebench.py:ALPHA"], [0.01, 0.05, 0.1],
       note="McNemar p at or below which ours and the reference disagree per instance (#922)"),
    _k("swebench_completion_timeout", ["evals/swebench.py:COMPLETION_TIMEOUT_S"], [600.0, 1800.0, 3600.0, 7200.0],
       note="seconds one 13k-token SWE-Llama completion may take before predict stops (#922)"),
    _k("swebench_fetch_timeout", ["evals/swebench.py:FETCH_TIMEOUT_S"], [30.0, 120.0, 600.0],
       note="seconds to fetch the reference results.json or all_preds.jsonl (#922)"),
    _k("swebench_margin", ["evals/swebench.py:MARGIN"], [0.05, 0.10, 0.15],
       note="largest applied-rate gap from the reference that still counts as agreement (#922)"),
    _k("swebench_max_tokens", ["evals/swebench.py:DEFAULT_MAX_TOKENS"], [1024, 2048, 4096, 8192],
       note="reply budget per SWE-Llama prompt; a reply cut short is a truncated patch that will not apply (#922)"),
]

_GREEDY = "the published run's decoding, replicated rather than chosen; the server's echo is recorded (#922)"
NOT_GATING = {
    **{f"evals/swebench.py:GREEDY[{k}]": _GREEDY
       for k in ("temperature", "top_k", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty",
                 "frequency_penalty", "dry_multiplier", "xtc_probability", "seed")},
    "evals/swebench.py:PROPS_TIMEOUT_S": "a /props miss leaves the receipt's server block empty; it refuses nothing (#922)",
}
