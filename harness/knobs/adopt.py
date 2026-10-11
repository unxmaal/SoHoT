"""Knobs of adoption tests (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("adopt_alpha", ["harness/adopt.py:ALPHA"], [0.01, 0.025, 0.05, 0.1],
       note="level of the first paired test on a holdout; later ones face it over their comparison count (#698)"),
    _k("adopt_effect", ["harness/power.py:EFFECT", "harness/power.py:DEFAULT_EFFECT"], [0.05, 0.1, 0.2, 0.3],
       note="smallest per-cell gain a lane adopts for; a null that could not see it is not a loss (#698)"),
    _k("unseen_rate", ["harness/power.py:UNSEEN"], [0.25, 0.5, 0.75],
       note="pass rate a plan assumes for an incumbent with no draws; such a plan is unmeasured (#698)"),
]
