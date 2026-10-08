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


def test_mutation_testing_runs_nightly_and_never_on_a_pull_request():
    """Mutating six modules costs minutes per module; #492 F3 keeps it off the PR path."""
    doc, _ = _ci()
    job = doc["jobs"]["mutation"]
    assert "schedule" in job["if"] and "pull_request" not in job["if"], job["if"]
    run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "make mutation" in run
    assert "mutation" in doc["jobs"]["report-nightly"]["needs"]


def test_make_mutation_redirects_its_output():
    make = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    recipe = make.split("\nmutation:", 1)[1].split("\n\n", 1)[0]
    assert "tests.gauntlet.mutation run" in recipe and "> " in recipe


def test_a_new_pages_publish_cancels_a_stuck_one():
    """A deploy stuck waiting on the environment held the group for 16 hours (#570)."""
    pages = CI.parent / "pages.yml"
    doc = yaml.safe_load(pages.read_text(encoding="utf-8"))
    assert doc["concurrency"]["cancel-in-progress"] is True


def test_linux_runs_the_suite_once_and_coverage_rides_on_it():
    """A second full pytest pass for coverage put check-linux over its timeout (#623)."""
    doc, _ = _ci()
    steps = doc["jobs"]["check-linux"]["steps"]
    runs = [s for s in steps if "pytest" in s.get("run", "") or "make check" in s.get("run", "")]
    assert len(runs) == 1 and "make check" in runs[0]["run"], [s.get("name") for s in runs]
    assert "--cov" in runs[0].get("env", {}).get("PYTEST_ADDOPTS", "")


def _linux_step(steps, pred):
    return next(i for i, s in enumerate(steps) if pred(s))


def test_a_slow_apt_mirror_fails_its_own_step_rather_than_cancelling_make_check():
    """A 13-minute apt download ate the job budget and cancelled make check (#647)."""
    doc, _ = _ci()
    job = doc["jobs"]["check-linux"]
    apt = job["steps"][_linux_step(job["steps"], lambda s: s.get("name") == "Tools make check needs")]
    assert isinstance(apt.get("timeout-minutes"), int) and 1 <= apt["timeout-minutes"] <= 8
    # make check alone takes about 14 minutes on this runner.
    assert job["timeout-minutes"] > apt["timeout-minutes"] + 20


def test_apt_packages_are_cached_on_the_package_list():
    """The .deb files come from a cache keyed on the package list, saved before make check (#647)."""
    doc, _ = _ci()
    steps = doc["jobs"]["check-linux"]["steps"]
    restore = _linux_step(steps, lambda s: s.get("uses", "").startswith("actions/cache/restore@"))
    apt = _linux_step(steps, lambda s: s.get("name") == "Tools make check needs")
    save = _linux_step(steps, lambda s: s.get("uses", "").startswith("actions/cache/save@"))
    check = _linux_step(steps, lambda s: s.get("name") == "make check")
    assert restore < apt < save < check
    key = steps[restore]["with"]["key"]
    assert key == steps[save]["with"]["key"] and "steps." in key
    assert "Dir::Cache::archives" in steps[apt]["run"]
    assert "cache-hit" in steps[save]["if"]
