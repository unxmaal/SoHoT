"""Knobs of the screen tier and the sampling it runs media candidates at (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("repo_screen_cases", ["evals/repo_screen.py:CASES"], [12, 24, 36, 54], lanes=("repo",), receipt="knobs",
       limit="repo_screen_cases", unit="cases", unrecorded=24, note="repo exam cases a candidate's screen runs, stratified by group x variant; 24 is ~2.8 h for a 27B "
            "at ~3x Ornith's 142 s median case (run 571), under a night, and leaves every one of the 8 strata "
            "two or more cases bar the 1-case pilot and infovore symptom ones (#1176)"),
    _k("screen_cases", ["evals/run.py:SCREEN_CASES"], [1, 3, 6, 10], limit="screen_cases", unit="cases",
       note="most cases a screen draws per lane and language; a zero-pass screen it capped waits on it (#691)"),
    _k("screen_confidence", ["harness/screen.py:SCREEN_CONFIDENCE"], [0.8, 0.9, 0.95, 0.99], limit="screen_confidence", unit="share",
       note="chance a model as good as the incumbent passes one screen case; sets how many it draws (#691)"),
    _k("screen_outside_votes", ["evals/repo_screen.py:OUTSIDE_VOTES"], [2, 3, 4],
       note="independent third-party benchmarks ranking a candidate above Ornith before its failed repo screen "
            "is rerun rather than declined; Eric's rule on #1176, unmeasured"),
    _k("screen_repeats", ["evals/repo_screen.py:REPEATS"], [2, 3, 5],
       note="extra draws of a failed repo screen the outside votes disagree with, pooled before declining; "
            "same-config Ornith runs 466/472 differ on 4 of 39 cases (FINDING #597), so one draw is noisy (#1176)"),
    _k("screen_size", ["evals/run.py:SCREEN_PARAMS[width]", "evals/run.py:SCREEN_PARAMS[height]"], [256, 512, 1024],
       limit="screen_size", unit="pixels", note="pixels an image or video screen is shrunk to; a zero-pass media screen waits on it (#691)"),
    _k("stt_screen_max_wer", ["harness/screen.py:SCREEN_MAX_WER"], [0.3, 0.5, 0.8],
       note="corpus WER under which an stt screen counts as transcribed; a plausibility bound, unmeasured (#1007)"),
]

NOT_GATING = {
    "evals/repo_screen.py:verdict(outside_votes)": "how many outside benchmarks favour the candidate, an input; "
    "OUTSIDE_VOTES is the gate it is held to (#1176)",
    **{f"harness/image_diffusers.py:FAMILY_SAMPLING[{f}][{k}]": "the value the family's own model card names (#691)"
       for f in ("sdxl_turbo", "z_image_turbo", "stable_diffusion_3_5_large_turbo") for k in ("steps", "guidance")},
    "harness/rank.py:AGE_DAYS": "a queue-order weight's ramp: it orders the queue and never refuses a row (#881)",
}
