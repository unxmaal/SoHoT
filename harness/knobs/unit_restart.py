"""Knobs of unit restart (#2134)."""

KNOBS = []

NOT_GATING = {
    "harness/unit_restart.py:RESTART_TIMEOUT_S": "bound on an owner's restart press; a timeout is reported to the owner and no verdict reads it (#2134)",
}
