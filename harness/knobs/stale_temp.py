"""Knobs of stale temp (#1900)."""

KNOBS = []

NOT_GATING = {
    "harness/stale_temp.py:FLOOR_S": "a dead pid is the proof; the floor only spares a writer whose pid this machine cannot see (another pid namespace sharing the directory), whose write window is milliseconds (#1900)",
}
