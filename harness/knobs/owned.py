"""Knobs of owned (#1759)."""

KNOBS = []

NOT_GATING = {
    "harness/owned.py:TERM_GRACE_S": "the owner's TERM handler stops its children within it before the sender's own escalation; it gates no outcome (#1759)",
}
