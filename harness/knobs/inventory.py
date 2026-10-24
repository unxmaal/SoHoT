"""Knobs of `soh inventory time` (#1152)."""
from harness.knobs.base import _k

KNOBS = [
    _k("inventory_gpu_busy_ratio", ["harness/inventory_time.py:GPU_BUSY_RATIO"], [0.25, 0.5, 0.75],
       note="GPU active ratio at or above which a power sample reads the GPU busy (#1152)"),
    _k("inventory_gpu_busy_watts", ["harness/inventory_time.py:GPU_BUSY_WATTS"], [5.0, 10.0, 20.0],
       note="GPU watts at or above which a sample with no active ratio reads busy (#1152)"),
    _k("inventory_morning_span", ["harness/inventory_time.py:MORNING_SPAN_SECONDS"], [60.0, 300.0, 900.0],
       note="seconds after the morning unit's start line a delegation counts as the morning brief's (#1152)"),
    _k("inventory_recent_days", ["harness/inventory_time.py:RECENT_DAYS"], [7, 14, 30],
       note="days the recent window of the effort account reaches back (#1152)"),
    _k("inventory_sweep_floor", ["harness/inventory_time.py:SWEEP_FLOOR_SECONDS"], [300.0, 600.0, 1800.0],
       note="seconds a sweep start line with no later sign of life is charged as discovery (#1152)"),
]

NOT_GATING = {
    "harness/inventory_time.py:HOUR": "seconds in an hour (#1152)",
    "harness/inventory_time.py:gh_items(limit)": "how many PRs and issues gh lists; above the repo's count, "
                                                 "so every item is read (#1152)",
    "harness/inventory_time.py:gh_items.ask->run(timeout)": "how long one gh list may take; a timeout reports "
                                                            "the effort account unavailable (#1152)",
}
