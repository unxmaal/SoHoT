"""Knobs of how much a sweep screens, each screen fetching what it runs (#1084, #2015)."""
from harness.knobs.base import _k

C = "harness/ceiling.py"

KNOBS = [
    _k("discover_top", ["scripts/serve-discover.sh:DISCOVER_TOP"], [0, 1, 3, 10],
       note="a count that overrides the sweep ceiling sizing the night's screen and measure; 0 is none (#1084)"),
    _k("fetch_passed_over", ["harness/rank.py:PASSED_OVER"], [0.0, 0.25, 0.5, 1.0], unit="points",
       note="rank.value per day a screen's share of the sweep ceiling passed a fetchable row over, since its "
            "last screen; 2026-10-26 projection of the same shape under the fetch budget: rows never reached "
            "55 off, 24 at 0.25, 19 at 0.5 (#1288, #2020)"),
    _k("fetch_passed_over_max", ["harness/rank.py:PASSED_OVER_MAX"], [6.0, 15.0, 30.0], unit="points",
       note="most the pass-over term adds; a cap reached before the queue's value spread stops the aging: same "
            "projection at 0.5/day leaves 51-58 unfetched capped at 6 or 9, 41 at 15, 19 at 30 or none (#1288)"),
    _k("fetch_progress_poll", ["harness/downloads.py:PROGRESS_POLL_S"], [10.0, 60.0, 300.0], unit="s",
       note="seconds between looks at the bytes a download wrote, each growth a heartbeat beat; 60 s is 1/60 of "
            "sweep_check_stall and 2.3 GiB at the slowest night rate, 39.6 MiB/s (#771)"),
    _k("measure_wip", ["harness/wip.py:LIMIT"], [1, 2, 3, 4], unit="measures",
       note="most screened, paused and running measures one open lane holds; the screen pulls a lane's next candidate only below it (#2165)"),
    _k("screen_days", [f"{C}:SCREEN_DAYS"], [7, 30, 90],
       note="days of screen verdicts the seconds-per-screen estimate reads (#1084)"),
    _k("screen_estimate", [f"{C}:SCREEN_S"], [120.0, 300.0, 600.0, 1200.0],
       note="seconds per screen when the store has none to measure; live mean 453 s on 2026-10-21 (#1084)"),
    _k("screen_fraction", [f"{C}:SCREEN_FRACTION"], [0.25, 0.5, 0.75],
       note="share of the sweep ceiling the screen may take; the measure step has the rest (#1084)"),
]

NEVER_CUTS = {
    "harness/downloads.py:PROGRESS_POLL_S": "seconds between looks at a download's bytes; it paces heartbeat beats and stops nothing",
    "harness/ceiling.py:SCREEN_DAYS": "how far back the per-screen time is averaged; the screen count it feeds records its "
                                      "cut as screen_fraction (#1084)",
    "harness/ceiling.py:SCREEN_S": "the per-screen time assumed before any screen is stored; the screen count it feeds "
                                   "records its cut as screen_fraction (#1084)",
}
