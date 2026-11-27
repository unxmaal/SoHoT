"""Knobs of pipeline yield (#2163)."""

KNOBS = []

NOT_GATING = {
    "harness/pipeline_yield.py:RED_SHARE": "only colours the status page marker; no verdict or job reads it (#2163)",
    "harness/pipeline_yield.py:trend(days)": "the morning line's comparison window; nothing is decided on it (#2163)",
}
