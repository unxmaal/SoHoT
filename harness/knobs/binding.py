"""Knobs of when a knob counts as binding (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("binding_fraction", ["harness/binding.py:BINDING_FRACTION"], [0.02, 0.05, 0.1, 0.25],
       note="share of a lane's rows hitting a limit at which its knob is reported binding"),
    _k("binding_min_hits", ["harness/binding.py:BINDING_MIN_HITS"], [1, 3, 5, 10],
       note="fewer hits than this is never binding"),
    _k("binding_window", ["harness/binding.py:BINDING_WINDOW_DAYS"], [7, 14, 30, 90],
       note="days of runs and verdicts a binding count reads"),
]
