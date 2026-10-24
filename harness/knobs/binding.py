"""Knobs of when a knob counts as binding (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("binding_fraction", ["harness/binding.py:BINDING_FRACTION"], [0.02, 0.05, 0.1, 0.25],
       note="share of a lane's rows hitting a limit at which its knob is reported binding"),
    _k("binding_min_hits", ["harness/binding.py:BINDING_MIN_HITS"], [1, 3, 5, 10],
       note="fewer hits than this is never binding"),
    _k("binding_window", ["harness/binding.py:BINDING_WINDOW_DAYS"], [7, 14, 30, 90],
       note="days of runs and verdicts a binding count reads"),
    _k("fallback_min_cases", ["harness/sweeps.py:FALLBACK_MIN_CASES"], [6, 10, 20, 40],
       note="measured cases a sweep fallback model's newest run needs before its pass rate ranks against a smaller "
            "run's; below it a run ranks after every run at or above it, each tier by the Wilson 95% lower bound. "
            "2026-10-23 repo: Qwopus3.6 3 of 6 (run 570) outranked Ornith 12 of 108 (run 571) and took about 9 "
            "GPU-h; on those 6 cases Ornith passed 2, a one-case gap. The Wilson lower bound alone still inverts "
            "(3 of 6 0.19 vs 12 of 108 0.06); at 20 cases its half-width at p=0.5 is 0.2, at 6 it is 0.31 (#1179)"),
    _k("lane_min_cuts", ["harness/sweeps.py:LANE_MIN_CUTS"], [5, 10, 20, 40],
       note="cuts given more room on a lane's other models, none passing, before a model with no ladder of its own "
            "is not swept on the reply budget. 2026-10-24 store, repo at 32768: 0 of 22 (runs 557 and 474, 484 and "
            "485); the Qwopus3.6 sweep it would have stopped (jobs 0141-0145) then converted 0 of 9 cut at 8000 and "
            "0 of 5 cut at 16384. 0 of 20 bounds the lane's conversion rate under 15% at 95% (#1177)"),
]
