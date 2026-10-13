"""Knobs of adoption tests (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("adopt_alpha", ["harness/adopt.py:ALPHA"], [0.01, 0.025, 0.05, 0.1],
       note="level of the first paired test on a holdout; later ones face it over their comparison count (#698)"),
    _k("adopt_effect", ["harness/power.py:EFFECT", "harness/power.py:DEFAULT_EFFECT"], [0.05, 0.1, 0.2, 0.3],
       note="smallest per-cell gain a lane adopts for; a null that could not see it is not a loss (#698)"),
    _k("deadline_grace", ["harness/power.py:DEADLINE_GRACE"], [1.0, 1.25, 1.5, 2.0],
       note="how far past max(budget, projection) a paired run may go before it is stopped inconclusive (#673, #696)"),
    _k("decode_tok_s", ["harness/power.py:DECODE_TOK_S", "harness/completion.py:MIN_DECODE_TOK_S"],
       [15.0, 25.0, 50.0, 100.0, 145.0, 200.0], keyed="machine",
       note="decode rate per machine a paired run's reply-budget estimate assumes; prices the deadline, not a grade (#696)"),
    _k("lead_p", ["harness/power.py:LEAD_P"], [0.05, 0.1, 0.2],
       note="paired p under which an underpowered verdict that leaned to the challenger is a lead (#806)"),
    _k("sweep_ceiling_h", ["harness/power.py:SWEEP_CEILING_H"], [4.0, 6.0, 8.0],
       note="hours a discover loop runs from its start; no measurement is planned to end past it (#806)"),
    _k("unseen_rate", ["harness/power.py:UNSEEN"], [0.25, 0.5, 0.75],
       note="pass rate a plan assumes for an incumbent with no draws; such a plan is unmeasured (#698)"),
]
