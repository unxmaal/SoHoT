"""Knobs of `soh review` and its weekly launchd unit (#1149)."""
from harness.knobs.base import _k

R = "harness/review.py"

KNOBS = [
    _k("review_call_timeout_s", [f"{R}:CALL_TIMEOUT_S"], [900.0, 1800.0, 3600.0], limit="review_call_timeout_s",
       unit="s", note="seconds one claude -p finder or refuter call may take; Opus loops of 20-40 requests took a "
                      "median 180 s and of 60-100 requests 447 s (store otel_events, 2026-10-25) (#1149)"),
    _k("review_candidates", [f"{R}:CANDIDATES"], [3, 5, 10], limit="review_candidates", unit="issues",
       note="findings one finder may report; each costs a sandboxed reproduction and a refuter call (#1149)"),
    _k("review_dedup_days", [f"{R}:DEDUP_DAYS"], [30, 90, 365],
       note="days back the dedup searches closed issues (open ones always); 90 covered every issue SoHoT had "
            "on 2026-10-25, the first opened 2026-09-07 (#1149)"),
    _k("review_hour", ["scripts/launchd.sh:REVIEW_HOUR"], [4, 5],
       note="local hour the weekly review starts: after the 03:00 audit, outside the 21:00-03:00 sweep window "
            "and before the 06:30 morning report; it waits out a sweep still running (#1149)"),
    _k("review_issue_limit", [f"{R}:ISSUE_LIMIT"], [500, 1000, 2000], limit="review_issue_limit", unit="issues",
       note="issues one gh issue list page holds; a full page files nothing, since the dedup could not see every "
            "issue; SoHoT had 63 open on 2026-10-25 (#1149)"),
    _k("review_max_findings", [f"{R}:MAX_FINDINGS"], [1, 3, 5], limit="review_max_findings", unit="issues",
       note="issues one run may file; 3 until soh review stats has 4 weeks of precision, so one bad week leaves "
            "at most 3 issues to close (#1149)"),
    _k("review_min_closed", [f"{R}:MIN_CLOSED"], [3, 5, 10],
       note="closed review-bot issues a dimension needs before its precision can switch it off (#1149)"),
    _k("review_min_precision", [f"{R}:MIN_PRECISION"], [0.3, 0.5, 0.7],
       note="share of a dimension's closed issues closed as completed below which the next run skips it; "
            "below one half, closing its issues costs Eric more than they find (#1149)"),
    _k("review_precision_weeks", [f"{R}:PRECISION_WEEKS"], [4, 8],
       note="weeks a dimension files before its precision can switch it off (#1149)"),
    _k("review_quote_slack", [f"{R}:QUOTE_SLACK"], [0, 3, 10],
       note="lines either side of a finding's stated line its quote may sit on; models miscount by a line or "
            "two, a wider window lets a quote match a different line (#1149)"),
    _k("review_repro_timeout_s", [f"{R}:REPRO_TIMEOUT_S"], [60.0, 300.0, 900.0], limit="review_repro_timeout_s",
       unit="s", note="seconds one sandboxed reproduction may take; the fixture's probe took under 6 s, the "
                      "slowest SoHoT loop test about 12 s; a timeout counts as not reproduced (#1149)"),
    _k("review_token_budget", [f"{R}:TOKEN_BUDGET"], [10_000_000, 20_000_000, 40_000_000],
       limit="review_token_budget", unit="tokens",
       note="claude -p tokens one run may spend (input, output, cache read and creation summed), counted as plan "
            "usage in tokens; Opus loops of 20-40 requests spent a median 5.0M (p90 10.8M, 36 loops in "
            "otel_events), so four finders and their refuters fit near 20M; no call starts once it is spent (#1149)"),
    _k("review_turns", [f"{R}:TURNS"], [20, 30, 60], limit="review_turns", unit="turns",
       note="--max-turns of each claude -p call; past 40 requests an Opus loop's median doubled to 11.3M tokens "
            "(otel_events), so 30 keeps a finder in the 5M band; one that runs out reports nothing (#1149)"),
    _k("review_wait_h", [f"{R}:WAIT_H"], [1.0, 3.0, 6.0],
       note="hours the review waits for a running discovery loop before skipping the week, as the canary does "
            "(#1149)"),
    _k("review_weekday", ["scripts/launchd.sh:REVIEW_WEEKDAY"], [0, 6],
       note="launchd weekday (0 Sunday) the review runs; the canary has Saturday 04:00, so the two weekly night "
            "jobs never share a morning (#1149)"),
]

NOT_GATING = {
    f"{R}:GH_TIMEOUT_S": "how long one gh or git call may take; a failure reads as unchecked and files nothing (#1149)",
    f"{R}:OUTPUT_LINES": "lines of a reproduction's output an issue body quotes; presentation only (#1149)",
    f"{R}:POLL_S": "how often the review re-reads the loop heartbeat while it waits; latency only (#1149)",
}

NEVER_CUTS = {
    f"{R}:DEDUP_DAYS": "the window closed issues are searched in; an issue older than it is never read, so no run "
                       "can see the window bind (#1149)",
    "scripts/launchd.sh:REVIEW_HOUR": "the hour the weekly unit starts; a schedule cuts no work (#1149)",
    "scripts/launchd.sh:REVIEW_WEEKDAY": "the day the weekly unit starts; a schedule cuts no work (#1149)",
}
