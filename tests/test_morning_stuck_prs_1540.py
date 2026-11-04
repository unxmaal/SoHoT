"""`soh morning` names each open PR whose newest check-macos is cancelled or failed, and how long ago. #1540."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from harness import morning
from harness.commands import morning as morning_cmd

NOW = datetime(2026, 11, 4, 20, 40, tzinfo=timezone.utc).timestamp()


def _check(conclusion, started, completed, name="check-macos"):
    status = "COMPLETED" if conclusion else "IN_PROGRESS"
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion,
            "startedAt": started, "completedAt": completed or "0001-01-01T00:00:00Z", "workflowName": "check"}


SKIPPED = _check("SKIPPED", "2026-11-04T16:19:31Z", "2026-11-04T16:19:31Z", name="check-linux")
PRS = [
    {"number": 1539, "title": "Reverify a grown case set", "url": "https://x/pull/1539",
     "statusCheckRollup": [_check("CANCELLED", "2026-11-04T16:19:31Z", "2026-11-04T16:34:33Z"), SKIPPED]},
    {"number": 1537, "title": "STT canary power", "url": "https://x/pull/1537",
     "statusCheckRollup": [_check("CANCELLED", "2026-11-04T15:51:16Z", "2026-11-04T16:06:20Z"),
                           _check("", "2026-11-04T20:48:29Z", None), SKIPPED]},
    {"number": 1536, "title": "Engine is not an engine", "url": "https://x/pull/1536",
     "statusCheckRollup": [_check("FAILURE", "2026-11-04T20:00:00Z", "2026-11-04T20:20:00Z")]},
    {"number": 1535, "title": "Green", "url": "https://x/pull/1535",
     "statusCheckRollup": [_check("SUCCESS", "2026-11-04T19:00:00Z", "2026-11-04T19:20:00Z")]},
    {"number": 1534, "title": "No checks yet", "url": "https://x/pull/1534", "statusCheckRollup": []},
]


def _gh(prs, calls):
    def gh(argv):
        calls.append(argv)
        return json.dumps(prs)
    return gh


def test_a_stuck_pr_reaches_the_brief_with_how_long_ago_and_a_rerun_in_flight_does_not():
    calls = []
    got = morning.stuck_prs(NOW, gh=_gh(PRS, calls))
    assert calls[0][:4] == ["pr", "list", "--state", "open"]
    assert [p["number"] for p in got["prs"]] == [1536, 1539]
    lines = [morning.pr_line(p) for p in got["prs"]]
    assert lines == ["PR #1536 check-macos failure 20 min ago: Engine is not an engine",
                     "PR #1539 check-macos cancelled 4.1 h ago: Reverify a grown case set"]
    r = {"ci": {"available": False}, "sweep": {"loop": {"in_window": True, "status": "finished", "rc": 0}},
         "watchdog": [], "deploy": {}, "stale": [], "pulls": got}
    assert morning.needs(r) == lines
    shown = morning_cmd.render_prs(got)
    assert shown[0] == "prs       2 open PR(s) with check-macos cancelled or failed"
    assert shown[2].endswith("PR #1539 check-macos cancelled 4.1 h ago: Reverify a grown case set")


def test_an_unread_pr_list_is_said_and_a_skipped_read_says_nothing():
    def broken(argv):
        raise RuntimeError("gh pr list: rc 4: auth required")
    got = morning.stuck_prs(NOW, gh=broken)
    assert got == {"available": False, "why": "gh pr list: rc 4: auth required", "prs": []}
    assert morning_cmd.render_prs(got) == ["prs       unavailable: gh pr list: rc 4: auth required"]
    assert morning_cmd.render_prs(None) == []


def test_ago_reads_minutes_hours_then_days():
    assert [morning._ago(s) for s in (None, 600, 4 * 3600, 3 * 86400)] == [
        "at a time not recorded", "10 min ago", "4.0 h ago", "3 d ago"]
