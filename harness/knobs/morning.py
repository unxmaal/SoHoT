"""Knobs of `soh morning` and its launchd unit (#867)."""
from harness.knobs.base import _k

M = "harness/morning.py"

KNOBS = [
    _k("morning_ci_fresh", [f"{M}:CI_FRESH_S"], [24 * 3600.0, 30 * 3600.0, 48 * 3600.0],
       note="seconds old a scheduled nightly run may be and still count as last night's; an older one never notifies (#867)"),
    _k("morning_hours", ["scripts/launchd.sh:MORNING_HOURS"], [5, 6, 7],
       note="local hour the morning unit reports last night and notifies if something needs a person (#867)"),
    _k("morning_minute", ["scripts/launchd.sh:MORNING_MINUTE"], [0, 30],
       note="minute past morning_hours the morning unit fires (#867)"),
    _k("morning_stall_days", [f"{M}:STALL_DAYS"], [7.0, 14.0, 30.0],
       note="days a ranked-head candidate may wait undownloaded in one state before the morning says so (#925)"),
    _k("morning_stall_head", [f"{M}:STALL_HEAD"], [3, 10, 25],
       note="how much of each wanted lane's ranked head the morning stall line watches (#925)"),
]

NOT_GATING = {
    f"{M}:HEADLINE_CHARS": "characters of the condensed headline shown; presentation only (#867)",
    f"{M}:HEADLINE_LINES": "lines of what needs a person the headline shows; the rest are counted (#867)",
    f"{M}:GH_TIMEOUT_S": "how long gh may take; a timeout reports nightly CI unavailable (#867)",
    f"{M}:GIT_TIMEOUT_S": "how long a git fetch or rev-parse of the deploy checkout may take; a timeout reports it unavailable (#867)",
    f"{M}:MODEL_TIMEOUT_S": "how long the local model may take to condense the headline; past it the deterministic one is used (#867)",
    f"{M}:MODEL_MAX_TOKENS": "reply budget for the condensed headline; presentation only (#867)",
}

NEVER_CUTS = {
    "scripts/launchd.sh:MORNING_HOURS": "the hour the morning report runs; a schedule cuts no work (#1087)",
    "scripts/launchd.sh:MORNING_MINUTE": "the minute past the hour the morning report runs; a schedule cuts no work (#1087)",
}
