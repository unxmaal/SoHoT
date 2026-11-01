"""Limits of the discovery store's own bookkeeping (#1087)."""

KNOBS = []

#: Limits that pace or label store work and can never cut it.
NEVER_CUTS = {
    "harness/memory_store/transitions.py:RETEST_AFTER_SECONDS": "seconds until a rejection is asked again; it schedules "
                                                                "a retest and RETESTS decides how many, so none is dropped",
    "harness/memory_store/transitions.py:decide(upstream_idle_days)": "a fact about the upstream written into the "
                                                                       "verdict; decide records it and gates nothing on it",
}
