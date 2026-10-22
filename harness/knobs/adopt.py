"""Knobs of adoption tests (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("adopt_alpha", ["harness/adopt.py:ALPHA"], [0.01, 0.025, 0.05, 0.1],
       note="level of the first paired test on a holdout; later ones face it over their comparison count (#698)"),
    _k("adopt_effect", ["harness/power.py:EFFECT", "harness/power.py:DEFAULT_EFFECT"], [0.05, 0.1, 0.2, 0.3],
       note="smallest per-cell gain a lane adopts for; a null that could not see it is not a loss (#698)"),
    _k("deadline_grace", ["harness/power.py:DEADLINE_GRACE"], [1.0, 1.25, 1.5, 2.0],
       note="how far past its budget a paired run's slice may go before it is stopped; its rows are checkpointed and it resumes (#673, #813)"),
    _k("decode_tok_s", ["harness/power.py:DECODE_TOK_S", "harness/completion.py:MIN_DECODE_TOK_S"],
       [15.0, 25.0, 50.0, 100.0, 145.0, 200.0], keyed="machine",
       note="decode rate per machine a paired run's reply-budget estimate assumes; prices the deadline, not a grade (#696)"),
    _k("futility_cp", ["harness/looks.py:FUTILITY_CP"], [0.05, 0.1, 0.2],
       note="conditional power under the plan's effect below which a paused run that is not ahead stops for futility (#813)"),
    _k("incumbent_reuse_min_draws", ["harness/reuse.py:MIN_DRAWS"], [1, 2, 3],
       note="stored draws under the same content identity a (case, repeat) cell needs before the incumbent is "
            "not run on it; 1 because the paired gate pairs one incumbent draw with each challenger draw "
            "(paired.head_to_head, power.plan per cell) and a draw under the same bytes is exchangeable with a "
            "fresh one; replay of run 521 on a store copy keeps the futility verdict (#1094)"),
    _k("sweep_ceiling_h", ["harness/power.py:SWEEP_CEILING_H"], [4.0, 6.0, 8.0],
       note="hours a discover loop runs from its start; a measurement running at it pauses and resumes next sweep (#806, #813)"),
    _k("sweep_unused_s", ["harness/ceiling.py:UNUSED_S"], [1800.0, 3600.0, 7200.0],
       note="ceiling seconds a finished sweep may leave unused before soh morning names why (#1082)"),
    _k("unseen_rate", ["harness/power.py:UNSEEN"], [0.25, 0.5, 0.75],
       note="pass rate a plan assumes for an incumbent with no draws; such a plan is unmeasured (#698)"),
]
