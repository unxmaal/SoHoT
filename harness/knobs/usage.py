"""Knobs of the usage log (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("usage_drop_history", ["harness/usage.py:DROP_HISTORY"], [30 * 86400.0, 90 * 86400.0, 365 * 86400.0],
       note="seconds of usage-drop history kept; longer than any window a report reads (#700)"),
    _k("usage_min_requests", ["harness/usage.py:MIN_REQUESTS"], [10, 20, 50],
       note="requests or tool calls each side of a switch needs before it is compared (#481)"),
    _k("usage_queue", ["harness/usage.py:QUEUE_MAX", "harness/usage.py:BATCH_MAX"], [1000, 10000, 100000],
       note="usage rows queued before the writer drops them; drops are recorded and fail the audit (#700)"),
    _k("usage_session_gap", ["harness/usage.py:SESSION_GAP_S"], [60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0],
       unit="s",
       note="seconds between one client's requests that start a new session, the cluster of the usage z (#701); of "
            "118000 stored gateway gaps 24 lie within 1.5x of 600, the sparsest value, and 1605 within 1.5x of 300, "
            "the watchdog probe's 5-minute cadence (`soh floors`, #730)"),
    _k("usage_z_warn", ["harness/usage.py:Z_WARN"], [2.0, 3.0, 4.0],
       note="session-clustered z at which a rate rise after a switch is a regression and queues a reverify (#701)"),
]

NOT_GATING = {
    "harness/usage.py:SAMPLE_CHARS": "characters of prompt or completion kept per sample when text logging is on; "
                                     "no check reads them (#481)",
    **{f"harness/usage.py:_UNITS[{u}]": "seconds in a day, hour, minute or second (#706)" for u in "dhms"},
    "harness/context_report.py:rtk_gain->runner(timeout)": "how long `rtk gain` may take to report (#828)",
}

NEVER_CUTS = {
    "harness/usage.py:SESSION_GAP_S": "the gap that starts a client's next session; it groups requests into the "
                                      "clusters the z is taken over and drops none (#701)",
}
