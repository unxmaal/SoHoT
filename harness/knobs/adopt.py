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
    _k("holdout_family_share", ["harness/holdout.py:FAMILY_SHARE"], [0.34, 0.5, 0.67],
       note="largest share of a capped lane's holdout one case family holds; the excess goes to dev (#671)"),
    _k("holdout_saturated", ["harness/holdout.py:SATURATED"], [0.9, 0.95, 0.99],
       note="holdout pass share at or above which an incumbent leaves nothing to separate and reads as saturated (#479)"),
    _k("human_enough", ["harness/human.py:ENOUGH"], [1, 3, 5],
       note="answers a pairing needs before a person's lane verdict counts; diffusion lanes vary at a pinned seed (RULE #280, #274)"),
    _k("incumbent_reuse_min_draws", ["harness/reuse.py:MIN_DRAWS"], [1, 2, 3],
       note="stored draws under the same content identity a (case, repeat) cell needs before the incumbent is "
            "not run on it; 1 because the paired gate pairs one incumbent draw with each challenger draw "
            "(paired.head_to_head, power.plan per cell) and a draw under the same bytes is exchangeable with a "
            "fresh one; replay of run 521 on a store copy keeps the futility verdict (#1094)"),
    _k("power_fallback_repeat", ["harness/power.py:FALLBACK_REPEAT"], [1, 2, 3, 5],
       note="repeat a paired run takes when the powered one does not fit its budget (#591)"),
    _k("power_measuring_repeat", ["harness/power.py:MEASURING_REPEAT"], [2, 3, 4],
       note="least repeat of a stochastic lane whose within-case correlation is unmeasured, so the run measures it (#591)"),
    _k("power_plateau", ["harness/power.py:PLATEAU", "harness/power.py:PLATEAU_ABS"], [0.9, 0.95, 0.99],
       note="share of the best power, or within PLATEAU_ABS of it, past whose first repeat more repeats buy nothing (#591)"),
    _k("retests", ["harness/memory_store/transitions.py:RETESTS"], [1, 3, 5],
       note="times a screen or measure rejection is asked again, one retest_after apart, before it stands (#431)"),
    _k("retests_at_adopt", ["harness/memory_store/transitions.py:RETESTS_AT_ADOPT"], [0, 1, 2],
       note="retests of a decline at adopt; one checks a lost paired measurement, more re-ask a settled question (#881)"),
    _k("sweep_ceiling_h", ["harness/power.py:SWEEP_CEILING_H"], [4.0, 6.0, 8.0],
       note="hours a discover loop runs from its start; a measurement running at it pauses and resumes next sweep (#806, #813)"),
    _k("sweep_unused_s", ["harness/ceiling.py:UNUSED_S"], [1800.0, 3600.0, 7200.0],
       note="ceiling seconds a finished sweep may leave unused before soh morning names why (#1082)"),
    _k("unseen_rate", ["harness/power.py:UNSEEN"], [0.25, 0.5, 0.75],
       note="pass rate a plan assumes for an incumbent with no draws; such a plan is unmeasured (#698)"),
    _k("zero_pass_min_cases", ["harness/baseline.py:MIN_CASES"], [20, 30, 50],
       note="distinct stored cases a typed incumbent must pass none of before its lane takes the incumbent from "
            "measurement and a paired run against it is only a screen; a model passing 1 in 10 shows none of 30 "
            "4% of the time (0.9**30); repo's Qwen3-4B passed 0 of 41 (run 470) and 0 of 39 six times (480-485), "
            "Ornith 2-5 of 39 (472-474) (#1110)"),
]

NEVER_CUTS = {
    "harness/holdout.py:FAMILY_SHARE": "moves holdout cases to dev, never drops one; the split version names it (#671)",
    "harness/holdout.py:SATURATED": "labels an incumbent's holdout saturated in the report; nothing is skipped (#479)",
}
