"""Knobs of when a knob counts as binding (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("binding_fraction", ["harness/binding.py:BINDING_FRACTION"], [0.02, 0.05, 0.1, 0.25],
       note="share of a lane's rows hitting a limit at which its knob is reported binding"),
    _k("binding_min_hits", ["harness/binding.py:BINDING_MIN_HITS"], [1, 3, 5, 10],
       note="fewer hits than this is never binding"),
    _k("binding_window", ["harness/binding.py:BINDING_WINDOW_DAYS"], [7, 14, 30, 90],
       note="days of runs and verdicts a binding count reads"),
    _k("lane_min_cuts", ["harness/sweeps.py:LANE_MIN_CUTS"], [5, 10, 20, 40],
       note="cuts given more room on a lane's other models, none passing, before a model with no ladder of its own "
            "is not swept on the reply budget. 2026-10-24 store, repo at 32768: 0 of 22 (runs 557 and 474, 484 and "
            "485); the Qwopus3.6 sweep it would have stopped (jobs 0141-0145) then converted 0 of 9 cut at 8000 and "
            "0 of 5 cut at 16384. 0 of 20 bounds the lane's conversion rate under 15% at 95% (#1177)"),
]
