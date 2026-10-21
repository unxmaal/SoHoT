"""Knobs of how much a sweep fetches and screens, and of the daytime fetch that fills its buffer (#1084)."""
from harness.knobs.base import _k

C, D = "harness/ceiling.py", "harness/day_fetch.py"

KNOBS = [
    _k("day_fetch_budget", ["scripts/serve-fetch.sh:DAY_FETCH_GIB"], [20, 40, 80, 160],
       note="GiB one daytime fetch may download in all; the disk floor still holds (#1084)"),
    _k("day_fetch_cap", [f"{D}:CAP_MB_S"], [2.0, 5.0, 10.0, 25.0],
       note="MB/s a daytime fetch averages inside the capped hours; 43 MB/s uncapped on the Studio (#1084)"),
    _k("day_fetch_cap_end", [f"{D}:CAP_END_H"], [15, 16, 17, 18],
       note="local hour the daytime fetch's rate cap ends (#1084)"),
    _k("day_fetch_cap_start", [f"{D}:CAP_START_H"], [8, 9, 10],
       note="local hour the daytime fetch's rate cap begins (#1084)"),
    _k("day_fetch_night_end", [f"{D}:NIGHT_END_H"], [7, 8, 9],
       note="local hour the night ends and a daytime fetch may start (#1084)"),
    _k("day_fetch_night_start", [f"{D}:NIGHT_START_H"], [19, 20, 21],
       note="local hour a daytime fetch stops starting downloads and is ended, before the 21:00 sweep (#1084)"),
    _k("discover_top", ["scripts/serve-discover.sh:DISCOVER_TOP"], [0, 1, 3, 10],
       note="a count that overrides the sweep ceiling sizing the night's fetch, screen and measure; 0 is none (#1084)"),
    _k("screen_days", [f"{C}:SCREEN_DAYS"], [7, 30, 90],
       note="days of screen verdicts the seconds-per-screen estimate reads (#1084)"),
    _k("screen_estimate", [f"{C}:SCREEN_S"], [120.0, 300.0, 600.0, 1200.0],
       note="seconds per screen when the store has none to measure; live mean 453 s on 2026-10-21 (#1084)"),
    _k("screen_fraction", [f"{C}:SCREEN_FRACTION"], [0.25, 0.5, 0.75],
       note="share of the sweep ceiling the screen may take; the measure step has the rest (#1084)"),
]

NOT_GATING = {
    f"{D}:_release->proc.wait(timeout)": "how long an ended fetch child gets to exit before SIGKILL; no download gates on it",
    f"{D}:next_at->timedelta(days)": "one calendar day, to reach tomorrow's hour; arithmetic, not a choice",
    "harness/throttle.py:Received.close->self._proc.wait(timeout)": "how long nettop gets to exit before SIGKILL",
}
