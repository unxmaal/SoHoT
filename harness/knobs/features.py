"""Knobs of features (#2081)."""

KNOBS = []

NOT_GATING = {
    "harness/features.py:LAUNCHCTL_TIMEOUT_S": "bounds one read-only launchctl list for the status page; a timeout leaves the unit rows unknown, decides nothing (#2081)",
    "harness/features.py:LOG_TAIL": "bytes of a unit log read to find its last line; shown on the status page, decides nothing (#2081)",
}
