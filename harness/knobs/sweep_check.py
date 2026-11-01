"""Knobs of `soh sweep-check` and its launchd unit (#1062)."""
from harness.knobs.base import _k

S = "harness/sweep_check.py"

KNOBS = [
    _k("sweep_check_early", [f"{S}:EARLY_S"], [600.0, 1800.0, 3600.0],
       note="seconds; a sweep that finished rc 0 sooner than this after starting notifies as finished early (#1062)"),
    _k("sweep_check_stall", [f"{S}:STALL_S"], [1800.0, 3600.0, 3 * 3600.0],
       note="seconds without heartbeat progress, or the step's own deadline when longer, before the sweep reads as stalled (#1062)"),
    _k("sweep_check_start_slack", [f"{S}:START_SLACK_S"], [300.0, 900.0, 3600.0],
       note="seconds before the scheduled discover hour a loop's start still counts as tonight's sweep (#1062)"),
]

NOT_GATING = {
    f"{S}:PROBE_TIMEOUT_S": "how long launchctl print may take; a timeout reads as unknown, which notifies (#1062)",
}

NEVER_CUTS = {
    "harness/heartbeat.py:STALL_S": "labels a loop stalled in status lines; nothing stops or waits on it (#1087)",
    "harness/heartbeat.py:SWEEP_SLACK_S": "words the live audit's late-sweep warning; nothing is skipped (#1087)",
}
