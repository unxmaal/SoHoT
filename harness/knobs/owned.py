"""Knobs of owned (#1759)."""
from harness.knobs.base import _k

KNOBS = [
    _k("reap_after_kill", ["harness/reaping.py:REAP_TIMEOUT_S"], [5.0, 10.0, 30.0], unit="s",
       note="a reap after a kill that outlives it names the pid and its ps state, records this cut and returns; a kernel-stuck child would otherwise hang the caller (#1925)"),
]

NOT_GATING = {
    "harness/owned.py:TERM_GRACE_S": "the owner's TERM handler stops its children within it before the sender's own escalation; it gates no outcome (#1759)",
}
