"""Knobs of the watchdog's criteria: when a running job is judged wrong and when a trip escalates (#814)."""
from harness.knobs.base import _k

W = "harness/watchdog.py"
P = "harness/lane_probe.py"

KNOBS = [
    _k("availability_target", ["harness/availability.py:TARGET"], [0.95, 0.99, 0.999],
       note="weekly share of judged probes an adopted text lane should answer; revisit with two weeks measured (#924)"),
    _k("lane_probe_hold", [f"{P}:HOLD_S"], [300.0, 1800.0, 3600.0],
       note="seconds a slow probe's request is left to finish; the lane is not probed again until it does (#924)"),
    _k("lane_probe_max_tokens", [f"{P}:MAX_TOKENS", f"{P}:MAX_TOKENS_DEFAULT"], [2, 8, 16],
       note="reply tokens a known-answer probe allows past the lane's own table; too few cuts the answer off and "
            "reads as down (#924)"),
    _k("lane_probe_timeout", [f"{P}:TIMEOUT_S", f"{P}:TIMEOUT_DEFAULT_S"], [10.0, 30.0, 60.0, 120.0],
       note="seconds a probe waits before the lane reads as slow, never down; a busy queue or a 35B is slow (#924)"),
    _k("watchdog_day_end_hour", [f"{W}:DAY_END_HOUR"], [18, 20, 21, 22],
       note="local hour Eric's day ends; the discover agent fires at it (Decision #456)"),
    _k("watchdog_day_start_hour", [f"{W}:DAY_START_HOUR"], [6, 7, 8, 9],
       note="local hour Eric's day starts; GPU jobs past watchdog_daytime_gpu inside the day are paused"),
    _k("watchdog_daytime_gpu", [f"{W}:DAYTIME_GPU_S"], [1800.0, 3600.0, 7200.0],
       note="seconds a GPU job may run inside the day hours before it is paused for the night (Decision #456)"),
    _k("watchdog_escalate_after", [f"{W}:ESCALATE_AFTER"], [1, 2, 3, 5],
       note="prior trips of a criterion on one subject inside watchdog_escalate_window before its escalation"),
    _k("watchdog_escalate_window", [f"{W}:ESCALATE_WINDOW_S"], [900.0, 1800.0, 3600.0],
       note="seconds back the watchdog counts prior trips toward an escalation"),
    _k("watchdog_every", ["scripts/launchd.sh:WATCHDOG_EVERY_MIN"], [1, 5, 10, 15],
       note="minutes between watchdog wakes; how late any criterion can be seen"),
    _k("watchdog_fallback_max", [f"{W}:FALLBACK_MAX"], [5, 20, 50, 100],
       note="requests a serving node handed back in live_audit's window that read as a fallback spike"),
    _k("watchdog_idle_hold", [f"{W}:IDLE_HOLD_S"], [600.0, 1800.0, 3600.0],
       note="seconds the eval lock may be held with no SoHoT job running before it is a stuck holder"),
    _k("watchdog_long_run", [f"{W}:LONG_RUN_S"], [4 * 3600.0, 6 * 3600.0, 8 * 3600.0, 12 * 3600.0],
       note="seconds a sweep, job or unowned eval may run at night before the watchdog flags it"),
    _k("watchdog_long_run_day", [f"{W}:LONG_RUN_DAY_S"], [3600.0, 2 * 3600.0, 4 * 3600.0],
       note="the same inside the day hours (Decision #456)"),
    _k("watchdog_notify_every", [f"{W}:NOTIFY_EVERY_S"], [900.0, 3600.0, 4 * 3600.0],
       note="seconds between desktop notifications for one criterion on one subject; a repeating trip is recorded, not re-shown (#818)"),
    _k("watchdog_orphan_grace", [f"{W}:ORPHAN_GRACE_S"], [30.0, 120.0, 600.0],
       note="seconds an orphaned eval or job is left before it is reaped, so a parent mid-exit is not raced"),
    _k("watchdog_overrun_factor", [f"{W}:OVERRUN_FACTOR"], [1.5, 2.0, 3.0],
       note="observed over planned seconds per case that reads as a harness defect (Decision #456)"),
    _k("watchdog_overrun_min_cases", [f"{W}:OVERRUN_MIN_CASES"], [1, 3, 10],
       note="cases a run must finish before its observed rate is judged"),
    _k("watchdog_overrun_min_pairs", [f"{W}:OVERRUN_MIN_PAIRS"], [3, 5, 10],
       note="cases both candidates of a paired run must finish before the challenger is judged against the incumbent (#864)"),
    _k("watchdog_stall", [f"{W}:STALL_S"], [600.0, 1800.0, 3600.0],
       note="seconds with no case finished that read as a wedged run"),
    _k("watchdog_stall_cases", [f"{W}:STALL_CASES"], [5, 10, 20],
       note="planned cases' worth of time with no case finished that reads as wedged, when longer than watchdog_stall"),
    _k("watchdog_swapout_max", [f"{W}:SWAPOUT_MAX_PER_MIN"], [500.0, 2000.0, 10000.0],
       note="swapouts per minute while a job runs that read as memory trouble"),
]

NOT_GATING = {
    "harness/workqueue.py:WATCH_S": "how soon a worker with jobs running sees a job it may start beside them; "
                                    "it decides when, never whether (#1153)",
    "harness/workqueue.py:at_clock->timedelta(days)": "one calendar day: a clock time already past today means tomorrow (#900)",
    "harness/workqueue.py:night_start->timedelta(days)": "one calendar day: the night window's edges on yesterday, today "
                                                         "and tomorrow (#900)",
    "harness/workqueue.py:night_window->timedelta(days)": "one calendar day: a day start already past means "
                                                          "tomorrow's (#1020)",
    f"{P}:CLAIMS_FORMAT[json_schema][schema][properties][c][items][maxItems]":
        "the claims tuple's shape in the probe's known question, as smoke sends it; not a limit (#924)",
    f"{P}:CLAIMS_FORMAT[json_schema][schema][properties][c][items][minItems]":
        "the claims tuple's shape in the probe's known question, as smoke sends it; not a limit (#924)",
    f"{W}:GH_TIMEOUT_S": "how long one gh call may take when filing; a slow gh leaves the issue unfiled and says so (#814)",
    f"{W}:NOTIFY_TIMEOUT_S": "how long osascript may take to post one notification; a slow one is recorded as "
                             "notify failed and the row and log line still stand (#818)",
    f"{W}:PROBE_TIMEOUT_S": "how long one outside probe (ps, launchctl, gh, the gateway) may take; a slow probe "
                            "is a gap the wake reports, never a verdict (#814)",
    f"{W}:RESTART_TIMEOUT_S": "how long the watchdog waits on launchd.sh restart behind the GPU lock; it says it "
                              "is still waiting and tries again next wake (#814)",
    f"{W}:STOP_GRACE_S": "how long a stopped group has between TERM and KILL; the same role as "
                         "workqueue.CANCEL_GRACE_S (#814)",
}
