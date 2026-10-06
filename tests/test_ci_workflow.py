"""Which platforms CI runs, and when.

A pull request runs macOS only, so work moves at the speed of one runner.
Linux and Windows run nightly on main, on demand, or on a PR labelled
full-ci, and a nightly failure opens an issue so it cannot pass unseen.
"""
from pathlib import Path

import yaml

CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
DEFERRED = ("check-linux", "check-windows")
LABEL = "full-ci"


def _ci():
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as True.
    return doc, doc.get("on", doc.get(True))


def test_macos_runs_on_every_pull_request():
    doc, _ = _ci()
    assert "if" not in doc["jobs"]["check-macos"]


def test_linux_and_windows_skip_an_unlabelled_pull_request():
    doc, _ = _ci()
    for job in DEFERRED:
        cond = doc["jobs"][job].get("if", "")
        assert "pull_request" in cond and LABEL in cond, (job, cond)


def test_linux_and_windows_skip_a_push_to_main():
    """Every merge would otherwise queue them again, which is the wait this
    removes. The nightly run covers main."""
    doc, _ = _ci()
    for job in DEFERRED:
        assert "push" not in doc["jobs"][job].get("if", "push"), job
        assert "schedule" in doc["jobs"][job]["if"], job


def test_adding_the_label_starts_the_deferred_jobs():
    _, on = _ci()
    assert "labeled" in on["pull_request"]["types"]


def test_main_gets_every_platform_nightly_and_on_demand():
    _, on = _ci()
    assert on["schedule"] and on["schedule"][0]["cron"]
    assert "workflow_dispatch" in on


def test_a_nightly_failure_opens_an_issue():
    doc, _ = _ci()
    job = doc["jobs"]["report-nightly"]
    assert set(DEFERRED) | {"check-macos"} <= set(job["needs"])
    assert "failure()" in job["if"] and "schedule" in job["if"]
    assert job["permissions"]["issues"] == "write"
    run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "gh issue create" in run and "gh issue comment" in run, (
        "a second failing night comments on the open issue instead of filing another")
