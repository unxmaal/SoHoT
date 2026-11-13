"""Knobs of tether (#1761)."""

KNOBS = []

NOT_GATING = {
    "harness/tether.py:GRACE_S": "how long a dead owner's child has to exit on TERM before the watcher kills it; the child is stopped either way (#1761)",
    "harness/tether.py:POLL_S": "how soon the watcher sees its owner gone; it only delays the stop it makes (#1761)",
}
