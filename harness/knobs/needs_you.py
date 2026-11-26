"""Knobs of needs you (#2134)."""
from harness.knobs.base import _k

KNOBS = [
    _k("needs_you_settle", ["harness/needs_you.py:SETTLE_S"], [300, 600, 900], unit="s",
       note="seconds after a deploy ends that its stuck-looking pause and service checks stay out of the band: two monit cycles, "
            "one for lift to clear the pause and the checks to pass, one for the pass that reads them; the 11-26 pauses cleared 600 s "
            "after they began (#2153)"),
]

NOT_GATING = {
    "harness/needs_you.py:CLEAR_PASSES": "only delays the alert that a condition cleared; the band shows the current state at once (#2134)",
    "harness/needs_you.py:FAILED_WINDOW_S": "how long a failed job stays listed in the band; no queue or run decision reads it (#2134)",
    "harness/needs_you.py:PAUSED_GRACE_S": "how long a paused job may sit before the band lists it; no queue or run decision reads it (#2134)",
}
