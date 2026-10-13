"""Knobs of the usage log (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("usage_min_requests", ["harness/usage.py:MIN_REQUESTS"], [10, 20, 50],
       note="requests or tool calls each side of a switch needs before it is compared (#481)"),
    _k("usage_queue", ["harness/usage.py:QUEUE_MAX", "harness/usage.py:BATCH_MAX"], [1000, 10000, 100000],
       note="usage rows queued before the writer drops them; drops are recorded and fail the audit (#700)"),
    _k("usage_session_gap", ["harness/usage.py:SESSION_GAP_S"], [60.0, 300.0, 1800.0],
       note="seconds between one client's requests that start a new session, the cluster of the usage z (#701)"),
    _k("usage_z_warn", ["harness/usage.py:Z_WARN"], [2.0, 3.0, 4.0],
       note="session-clustered z at which a rate rise after a switch is a regression and queues a reverify (#701)"),
]

NOT_GATING = {
    **{f"harness/usage.py:_UNITS[{u}]": "seconds in a day, hour, minute or second (#706)" for u in "dhms"},
    "harness/context_report.py:rtk_gain->runner(timeout)": "how long `rtk gain` may take to report (#828)",
}
