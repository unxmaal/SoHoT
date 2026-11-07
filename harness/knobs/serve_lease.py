"""Knobs of serving's lease over measurement: the wait for a case boundary, the cut, the grace and the target (#1556)."""
from harness.knobs.base import _k

KNOBS = [
    _k("serve_lease_cut_factor", ["harness/serve_lease.py:CUT_FACTOR"], [1.5, 2.0, 4.0],
       note="times its planned seconds a case in flight may run before a waiting delegation has it cut (#1556)"),
    _k("serve_lease_cut_wait", ["harness/serve_lease.py:CUT_WAIT_S"], [10.0, 30.0, 120.0],
       note="seconds a delegation waits for a case it had cut to end before it refuses (#1556)"),
    _k("serve_lease_grace", ["harness/serve_lease.py:GRACE_S"], [30.0, 120.0, 600.0],
       note="seconds the serving lease outlives a delegation's answer, so a follow-up skips the swap back (#1556)"),
    _k("serve_lease_wait", ["harness/serve_lease.py:WAIT_S"], [60.0, 300.0, 900.0],
       note="seconds a delegation waits for a running eval to reach a case boundary before its case is cut (#1556)"),
    _k("serve_p95_target", ["harness/serve_lease.py:P95_TARGET_S"], [5.0, 10.0, 30.0],
       note="warm p95 seconds, wait included, the report holds decide and extract delegations to (#1556)"),
]

NEVER_CUTS = {
    "harness/serve_lease.py:GRACE_S": "how long a yielded eval keeps waiting after the last answer; the eval resumes "
                                      "after it and drops no case, a delay never a cut (#1556)",
    "harness/serve_lease.py:P95_TARGET_S": "flags a lane in soh delegated --report; it refuses, stops and drops "
                                           "nothing (#1556)",
}

NOT_GATING = {
    "harness/serve_lease.py:HELD_S": "how long a waiting or serving delegation's lease row stands; its live process "
                                     "keeps it and a dead one's is released when read (#1558)",
    "harness/item_lease.py:TTL_S": "how long a lease outlives its last beat; a live holder beats every third of it, so "
                                   "it frees only a place nobody keeps (#1558)",
    "harness/serve_lease.py:POLL_S": "how often a delegation or a yielding eval looks at the lease again; "
                                     "serve_lease_wait bounds the wait (#1556)",
    "evals/watch.py:Watch.yield_s": "seconds a run has yielded to serving so far, a running total (#1556)",
    "evals/watch.py:Watch.yield_since_case_s": "seconds yielded since the last finished case, a running total (#1556)",
}
