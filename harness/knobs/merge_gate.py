"""Knobs of merge gate (#2110)."""
from harness.knobs.base import _k

KNOBS = [
    _k("merge_gate_retries", ["harness/merge_gate.py:RETRY_MAX"], [3], unit="passes",
       note="Passes that start a tree and die before its verdict before the deploy poll stops queueing another for it; the Needs-you button still can (#2140)"),
    _k("merge_gate_step_timeout", ["harness/merge_gate.py:STEP_TIMEOUT_S"], [3600.0], unit="s",
       note="One step of the local merge gate (the suite, the Postgres suite, one module's mutation run) is cut and fails the verdict after this long; ci.yml gives its longest job 60 minutes (#2110)"),
    _k("merge_gate_wait", ["harness/merge_gate.py:WAIT_S", "harness/merge_gate.py:run_pass(wait)", "harness/merge_gate.py:_pass(wait)"], [3600.0, 7200.0, 14400.0], unit="s",
       note="how long a --pr call waits for the lock another pass holds (#2206)"),
]

NOT_GATING = {
    "harness/merge_gate.py:DESCRIPTION_MAX": "GitHub's own limit on a status description; the tree a verdict names sits in its first 45 characters, so the cut drops only the closing words (#2110)",
    "harness/merge_gate.py:LOCK_POLL_S": "how often a waiting call retries the lock; no verdict reads it (#2206)",
}
