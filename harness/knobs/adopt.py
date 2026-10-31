"""Knobs of adoption tests (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("adopt_alpha", ["harness/adopt.py:ALPHA"], [0.01, 0.025, 0.05, 0.1],
       note="level of the first paired test on a holdout; later ones face it over their comparison count (#698)"),
    _k("adopt_effect", ["harness/power.py:EFFECT", "harness/power.py:DEFAULT_EFFECT"], [0.05, 0.1, 0.2, 0.3],
       lane_values={"code": (0.03, 0.06, 0.12, 0.2), "repo": (0.08, 0.16, 0.2, 0.3), "svg": (0.06, 0.12, 0.2, 0.3),
                    "tts": (0.03, 0.06, 0.12, 0.2)}, unit="share",
       note="smallest per-cell gain a lane adopts for; a null that could not see it is not a loss (#698). Per lane "
            "it is the share of cells a same-config rerun flips each way (pooled within-case variance of the "
            "lane-metric draw), rounded up to 0.01, never under adopt_effect_floor. Store 2026-10-25, measure rows "
            "by lane, configs, cases measured twice, churn: claims 2/548 0.0009, code 39/1636 0.0575, decide 4/245 "
            "0, extract 6/500 0.0081, ocr 2/148 0.0078, pii 2/182 0, repo 3/152 0.1501, retrieval 2/203 0, stt "
            "8/1352 0.0417, svg 16/46 0.1100, tts 3/470 0.0501, web 11/55 0.0107; agent 28, image 23, music 11 and video 2 "
            "cases are under adopt_effect_min_cases and keep 0.20. Replaying the 220 stored adopt verdicts changes "
            "one: 11228 (code, MDE +0.14) becomes underpowered. `soh knobs effects --store COPY` re-derives (#725)"),
    _k("adopt_effect_floor", ["harness/effects.py:FLOOR"], [0.02, 0.05, 0.1],
       note="the least noise effect a lane registers when its same-config reruns never flip (decide, pii, "
            "retrieval churn 0); the gate still powers for adopt_min_effect when that is larger (#725, #1320)"),
    _k("adopt_effect_min_cases", ["harness/effects.py:MIN_CASES"], [10, 30, 100],
       note="cases measured twice under one config before a lane's churn sets its effect; at 30 the churn's "
            "relative standard error is about a quarter (#725)"),
    _k("adopt_min_effect", ["harness/power.py:MIN_EFFECT"], [0.05, 0.1, 0.15, 0.2], unit="share",
       note="the smallest per-cell gain worth a model switch; the gate powers for max(lane noise effect, this). "
            "Holdout cases power 0.8 needs on each incumbent's measured rates and rho, store 2026-10-26, against "
            "holdouts of 134-189: at 0.05 code 947 (noise 0.06), decide 293, extract 1160, ocr 690, pii 700, "
            "retrieval 836, tts over 2000; at 0.10 code 384, decide 146, extract 423, ocr 320, pii 349, retrieval "
            "417, tts 1734; at 0.15 code 196, decide 134 (enough), extract 249, ocr 208, pii 233, retrieval 278, "
            "tts 835; at 0.20 code 135 (enough), extract 175, ocr 154, pii 174, retrieval 208, tts 510. Replaying "
            "the 221 stored adopt verdicts, none changes class because of it (#1320)"),
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
       note="holdout score on the lane's rank key (winners.primary) at or above which an incumbent reads as saturated; a lower-is-better metric at or below 1 minus it (#479, #1267)"),
    _k("human_enough", ["harness/human.py:ENOUGH"], [1, 3, 5],
       note="answers a pairing needs before a person's lane verdict counts; diffusion lanes vary at a pinned seed (RULE #280, #274)"),
    _k("incumbent_reuse_min_draws", ["harness/reuse.py:MIN_DRAWS"], [1, 2, 3],
       note="stored draws under the same content identity a (case, repeat) cell needs before the incumbent is "
            "not run on it; 1 because the paired gate pairs one incumbent draw with each challenger draw "
            "(paired.head_to_head, power.plan per cell) and a draw under the same bytes is exchangeable with a "
            "fresh one; replay of run 521 on a store copy keeps the futility verdict (#1094)"),
    _k("look_interval_s", ["harness/looks.py:LOOK_INTERVAL_S"], [600.0, 1800.0, 3600.0, 7200.0], unit="s",
       note="seconds of a paired run between interim looks inside its budget; each look restarts evals.run "
            "with --resume, about 23 s before its first case on a repo resume (job 0196), so 1800 costs ~1.3% "
            "of the slice and looks every ~4-6 repo cells (Ornith 164 s + Qwen3.6 294 s a pair) or ~8-10 code "
            "cells (Ornith 56 s + Swift-Qwen3.8 174 s, job 0199); at 7200 (the 2 h power_budget_min) the run looks only when its budget ends, as before (#1353)"),
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
    "harness/looks.py:LOOK_INTERVAL_S": "sets when a paired run stops for an interim look; it resumes after the look "
                                        "unless the look decides, so no case is dropped (#1353)",
    "harness/effects.py:MIN_CASES": "read only when soh knobs effects derives power.EFFECT offline; no run is cut (#725)",
    "harness/holdout.py:FAMILY_SHARE": "moves holdout cases to dev, never drops one; the split version names it (#671)",
    "harness/holdout.py:SATURATED": "labels an incumbent's holdout saturated in the report; nothing is skipped (#479)",
    "harness/power.py:UNSEEN": "the pass rate a plan assumes for a case with no stored rows; the plan is marked "
                               "unmeasured and no case is dropped (#698)",
    "harness/reverify.py:DEFAULT_DAYS": "days between re-runs of a served model; a due model is re-run, never "
                                        "skipped (#408)",
}
