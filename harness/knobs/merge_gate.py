"""Knobs of merge gate (#2110)."""
from harness.knobs.base import _k

KNOBS = [
    _k("merge_gate_step_timeout", ["harness/merge_gate.py:STEP_TIMEOUT_S"], [3600.0], unit="s",
       note="One step of the local merge gate (the suite, the Postgres suite, one module's mutation run) is cut and fails the verdict after this long; ci.yml gives its longest job 60 minutes (#2110)"),
]

NOT_GATING = {
    "harness/merge_gate.py:DESCRIPTION_MAX": "GitHub's own limit on a status description; the tree a verdict names sits in its first 45 characters, so the cut drops only the closing words (#2110)",
}
