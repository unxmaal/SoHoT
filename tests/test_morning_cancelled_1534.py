"""`soh morning` names a cancelled nightly job as cancelled, at its timeout or before it, never as failed. #1534."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from harness import ci_budget, morning
from harness.commands import morning as morning_cmd

NOW = datetime(2026, 11, 4, 6, 30).timestamp()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh(jobs):
    start = NOW - 4 * 3600
    runs = [{"databaseId": 7, "status": "completed", "conclusion": "cancelled", "createdAt": _iso(start),
             "headSha": "c" * 40, "url": "https://x/runs/7"}]
    view = {"jobs": [{"name": n, "status": "completed", "conclusion": c, "url": f"https://x/{n}",
                      "startedAt": _iso(start), "completedAt": _iso(start + mins * 60)} for n, c, mins in jobs]}

    def gh(argv):
        return json.dumps(runs if argv[:2] == ["run", "list"] else view)
    return gh


def _needs(jobs):
    c = morning.ci(NOW, gh=_gh(jobs))
    return c, morning.needs({"ci": c, "sweep": {"loop": {"in_window": True, "status": "finished", "rc": 0}},
                             "watchdog": [], "deploy": {}, "stale": []})


def test_jobs_cancelled_at_their_timeout_read_cancelled_not_failed():
    linux, windows, mutation = (ci_budget.limit_minutes(k) for k in ("check-linux", "check-windows", "mutation"))
    c, needs = _needs([("check-windows", "cancelled", windows + 1.3), ("check-linux", "cancelled", linux + 2.9),
                       ("mutation (harness/adopt.py)", "cancelled", mutation + 5), ("check-macos", "success", 22)])
    assert not [n for n in needs if "failed" in n]
    assert needs == [f"nightly CI cancelled at its timeout: check-windows ({windows + 1.3:.0f} of {windows:g} min), "
                     f"check-linux ({linux + 2.9:.0f} of {linux:g} min), "
                     f"mutation (harness/adopt.py) ({mutation + 5:.0f} of {mutation:g} min)"]
    assert {j["name"]: j["cancel"] for j in c["jobs"]}["check-linux"] == "timeout"
    assert f"cancelled  check-linux: at its {linux:g} min timeout" in "\n".join(
        morning_cmd.render_ci(c))


def test_a_failure_is_failed_and_an_early_cancel_says_a_person_or_a_newer_run():
    c, needs = _needs([("check-windows", "failure", 12), ("check-linux", "cancelled", 4),
                       ("check-macos", "success", 22)])
    linux = ci_budget.limit_minutes("check-linux")
    assert needs == ["nightly CI failed: check-windows",
                     f"nightly CI cancelled before its timeout (by a person or a newer run): check-linux (4 of {linux:g} min)"]
    assert {j["name"]: j["cancel"] for j in c["jobs"]} == {"check-windows": "", "check-linux": "superseded",
                                                           "check-macos": ""}


def test_a_cancelled_job_with_no_times_or_no_workflow_entry_is_still_cancelled():
    c, needs = _needs([("report-x", "cancelled", 3)])
    assert needs == ["nightly CI cancelled: report-x (3 min; no timeout-minutes known for it)"]
