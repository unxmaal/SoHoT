"""A CI job says how much of its timeout it used and warns past 80% (#1146)."""
import yaml

from harness import ci_budget

WF = """
jobs:
  check-macos:
    timeout-minutes: 15
    steps: []
"""


def _wf(tmp_path):
    p = tmp_path / "ci.yml"
    p.write_text(WF, encoding="utf-8")
    return p


def test_the_limit_is_the_jobs_own_timeout_minutes(tmp_path):
    assert ci_budget.limit_minutes("check-macos", _wf(tmp_path)) == 15.0
    real = yaml.safe_load(ci_budget.WORKFLOW.read_text(encoding="utf-8"))
    assert ci_budget.limit_minutes("check-macos") == real["jobs"]["check-macos"]["timeout-minutes"]


def test_the_warning_starts_just_past_eighty_percent():
    assert ci_budget.report("j", 12 * 60, 15) == ("j: 12.0 of 15 min (80% of its timeout)", False)
    assert ci_budget.report("j", 12 * 60 + 6, 15)[1] is True


def _run(tmp_path, used_s, capsys):
    summary = tmp_path / "summary.md"
    env = {"GITHUB_JOB": "check-macos", "JOB_STARTED_S": "1000", "GITHUB_STEP_SUMMARY": str(summary)}
    rc = ci_budget.main(["--workflow", str(_wf(tmp_path))], environ=env, now=lambda: 1000 + used_s)
    return rc, capsys.readouterr().out, summary.read_text(encoding="utf-8")


def test_a_run_past_the_share_prints_a_github_warning_and_still_passes(tmp_path, capsys):
    rc, out, summary = _run(tmp_path, 13.5 * 60, capsys)
    assert rc == 0
    assert "::warning title=CI time::check-macos: 13.5 of 15 min (90% of its timeout)" in out
    assert "13.5 of 15 min" in summary and "over 80%" in summary


def test_a_run_well_under_prints_its_time_and_no_warning(tmp_path, capsys):
    rc, out, summary = _run(tmp_path, 6 * 60, capsys)
    assert rc == 0 and out.strip() == "check-macos: 6.0 of 15 min (40% of its timeout)"
    assert "::warning" not in out and "over" not in summary


def test_check_macos_stamps_its_start_and_reports_its_budget_on_every_outcome():
    doc = yaml.safe_load(ci_budget.WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["check-macos"]["steps"]
    runs = [s.get("run", "") for s in steps]
    stamp = next(i for i, r in enumerate(runs) if "JOB_STARTED_S=" in r and "GITHUB_ENV" in r)
    check = next(i for i, s in enumerate(steps) if s.get("name") == "make check")
    budget = next(i for i, r in enumerate(runs) if "harness.ci_budget" in r)
    assert stamp < check < budget
    assert steps[budget].get("if") == "always()"
    upload = next(s for s in steps if "upload-artifact" in s.get("uses", ""))
    assert upload["with"]["path"] == "/tmp/junit.xml" and upload.get("if") == "always()"


def test_check_macos_runs_one_worker_more_than_its_cores_through_the_variable_xdist_reads():
    """Three workers left 3 vCPUs a third idle (time -p); -n auto reads this variable (#1146)."""
    import inspect

    from xdist import plugin
    doc = yaml.safe_load(ci_budget.WORKFLOW.read_text(encoding="utf-8"))
    runs = "\n".join(s.get("run", "") for s in doc["jobs"]["check-macos"]["steps"])
    assert 'PYTEST_XDIST_AUTO_NUM_WORKERS=$(( $(sysctl -n hw.ncpu) + 1 ))' in runs
    assert "PYTEST_XDIST_AUTO_NUM_WORKERS" in inspect.getsource(plugin)
