"""Knobs of needs you (#2134)."""

KNOBS = []

NOT_GATING = {
    "harness/needs_you.py:CLEAR_PASSES": "only delays the alert that a condition cleared; the band shows the current state at once (#2134)",
    "harness/needs_you.py:FAILED_WINDOW_S": "how long a failed job stays listed in the band; no queue or run decision reads it (#2134)",
    "harness/needs_you.py:PAUSED_GRACE_S": "how long a paused job may sit before the band lists it; no queue or run decision reads it (#2134)",
}
