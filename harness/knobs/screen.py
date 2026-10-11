"""Knobs of the screen tier and the sampling it runs media candidates at (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("screen_cases", ["evals/run.py:SCREEN_CASES"], [1, 3, 6, 10], limit="screen_cases",
       note="most cases a screen draws per lane and language; a zero-pass screen it capped waits on it (#691)"),
    _k("screen_confidence", ["harness/screen.py:SCREEN_CONFIDENCE"], [0.8, 0.9, 0.95, 0.99], limit="screen_confidence",
       note="chance a model as good as the incumbent passes one screen case; sets how many it draws (#691)"),
    _k("screen_size", ["evals/run.py:SCREEN_PARAMS[width]", "evals/run.py:SCREEN_PARAMS[height]"], [256, 512, 1024],
       limit="screen_size", note="pixels an image or video screen is shrunk to; a zero-pass media screen waits on it (#691)"),
]

NOT_GATING = {
    **{f"harness/image_diffusers.py:FAMILY_SAMPLING[{f}][{k}]": "the value the family's own model card names (#691)"
       for f in ("sdxl_turbo", "z_image_turbo", "stable_diffusion_3_5_large_turbo") for k in ("steps", "guidance")},
}
