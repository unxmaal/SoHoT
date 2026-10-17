"""Knobs of `soh canary` and its weekly launchd unit (#919)."""
from harness.knobs.base import _k

C = "harness/canary.py"

KNOBS = [
    _k("canary_hour", ["scripts/launchd.sh:CANARY_HOUR"], [3, 4, 5],
       note="local hour the planted-candidate canary starts on its weekday, after the night's sweep (#919)"),
    _k("canary_stale_days", [f"{C}:STALE_DAYS"], [8, 15],
       note="days without a canary receipt after which soh morning says the canary is stale (#919)"),
    _k("canary_wait_h", [f"{C}:WAIT_H"], [1.0, 3.0, 6.0],
       note="hours the canary waits for a running discovery loop before skipping the week (#919)"),
    _k("canary_weekday", ["scripts/launchd.sh:CANARY_WEEKDAY"], [0, 6],
       note="launchd weekday (0 or 7 Sunday, 6 Saturday) the planted-candidate canary runs (#919)"),
]

NOT_GATING = {
    f"{C}:POLL_S": "how often the canary re-reads the loop heartbeat while it waits; latency only (#919)",
    f"{C}:PLANT_DEADLINE_S": "the GPU lock's declared deadline per plant, which a watchdog reads; gates no verdict (#919)",
}
