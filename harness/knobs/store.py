"""Limits of the discovery store's own bookkeeping (#1087) and of its Postgres container (#1507)."""
from harness.knobs.base import _k

S = "harness/store_service.py"

KNOBS = [
    _k("store_pg_dump_timeout", [f"{S}:DUMP_TIMEOUT_S"], [600, 1800, 3600], unit="s",
       note="seconds a pg_dump or pg_restore of the store may take inside its container; a timeout fails the deploy's "
            "backup or rollback loudly (#1507)"),
    _k("store_pg_up_timeout", [f"{S}:UP_TIMEOUT_S"], [60, 180, 600], unit="s",
       note="seconds `docker compose up --wait` may take to report the store's container healthy (#1507)"),
]

NOT_GATING = {
    "harness/store_copy.py:BATCH_ROWS": "rows fetched or written per round trip of a copy; every row is copied (#1507)",
    "harness/store.py:POOL_MAX": "connections a long-lived service keeps; a borrow past it waits for one to come back, "
                                 "it drops no work (#1507)",
    "harness/store.py:use_pool->ConnectionPool(min_size)": "connections the pool keeps open while idle (#1507)",
}

#: Limits that pace or label store work and can never cut it.
NEVER_CUTS = {
    "harness/memory_store/transitions.py:RETEST_AFTER_SECONDS": "seconds until a rejection is asked again; it schedules "
                                                                "a retest and RETESTS decides how many, so none is dropped",
    "harness/memory_store/transitions.py:decide(upstream_idle_days)": "a fact about the upstream written into the "
                                                                       "verdict; decide records it and gates nothing on it",
}
