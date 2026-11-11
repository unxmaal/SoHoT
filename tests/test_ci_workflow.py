"""Which platforms CI runs, and when.

A pull request runs macOS only, so work moves at the speed of one runner.
Linux and Windows run nightly on main, on demand, or on a PR labelled
full-ci, and a nightly failure opens an issue so it cannot pass unseen.
"""
import re
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


def test_a_pull_request_mutates_the_functions_it_changes():
    """#1663 and #1665 changed screen functions, tested them only in LEFT_OUT files, and merged before any mutation run (#1666)."""
    doc, _ = _ci()
    plan, job = doc["jobs"]["mutation-plan"], doc["jobs"]["mutation-changed"]
    assert plan["if"] == "github.event_name == 'pull_request'"
    assert plan["steps"][0]["with"]["fetch-depth"] == 0, "the merge base needs the base branch's history"
    assert 'tests.gauntlet.mutation changed --base "origin/$BASE_REF"' in "\n".join(s.get("run", "") for s in plan["steps"])
    assert job["needs"] == "mutation-plan" and job["if"] == "needs.mutation-plan.outputs.plan != ''"
    assert job["runs-on"] == "macos-latest", "mutmut runs the selection, which needs Apple Silicon"
    run = "\n".join(s.get("run", "") for s in job["steps"])
    assert '--function $f' in run and 'make mutation MUTATION_ARGS="$args" < /dev/null' in run


def test_each_mutated_module_is_its_own_job_so_one_timeout_cannot_void_the_rest():
    """#840: all six in one job grew 35 -> 89 min, then hit the 120-minute limit and reported nothing."""
    from tests.gauntlet import mutation
    doc, _ = _ci()
    job = doc["jobs"]["mutation"]
    legs = job["strategy"]["matrix"]["include"]
    assert sorted({leg["module"] for leg in legs}) == sorted(mutation.MODULES)
    for module in mutation.MODULES:
        shards = sorted(leg.get("shard", "") for leg in legs if leg["module"] == module)
        n = len(shards)
        assert shards == ([""] if n == 1 else [f"{k}/{n}" for k in range(1, n + 1)]), (module, shards)
    assert job["strategy"]["fail-fast"] is False
    run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "--module ${{ matrix.module }}${{ matrix.shard && format(' --shard {0}', matrix.shard) || '' }}" in run
    assert "matrix.shard" in job["name"], "two shards of one module need two job names"


def test_adopt_mutation_is_split_since_one_job_ran_past_its_limit():
    """#1588: mutation (harness/adopt.py) was cut at 120 min on six of seven nightlies 11-01..11-07."""
    doc, _ = _ci()
    legs = [leg for leg in doc["jobs"]["mutation"]["strategy"]["matrix"]["include"] if leg["module"] == "harness/adopt.py"]
    assert len(legs) >= 2


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


#: check-macos job p95 and max on the 3-vCPU M1 class, 20 full runs 2026-10-31..11-03 (harness.ci_history, #1520).
MACOS_3_VCPU_JOB_P95, MACOS_3_VCPU_JOB_MAX = 23.6, 25.3
#: A slow M1 host ran 1.4x the run before it (41692522061 vs 41687128099, #1520); 2.0x on 40020366592 (#1146).
MACOS_SLOW_HOST = 1.4


def test_macos_leaves_room_for_a_slow_host_and_is_still_a_hang_detector():
    """A slow host on the slow class passes; twice the slowest run would hide a regression (#720, #1146, #1520)."""
    from harness import ci_budget
    doc, _ = _ci()
    limit = doc["jobs"]["check-macos"]["timeout-minutes"]
    assert limit == ci_budget.MACOS_TIMEOUT_MIN
    assert MACOS_SLOW_HOST * MACOS_3_VCPU_JOB_P95 <= limit < 2 * MACOS_3_VCPU_JOB_MAX


#: Job minutes projected from the nightly cuts' last progress % (python -m harness.ci_history --job J, #1588), and the
#: whole Postgres suite's from push run 42412868007, cut at 99% after 36.2 min (#1584).
PROJECTED_JOB_MIN = {"check-linux": 34.4, "check-windows": 61.0, "check-postgres": 36.5}
#: Linux and Windows hosts vary less than the M1 class; check-postgres is on macos-latest, so MACOS_SLOW_HOST.
HOST_FACTOR = {"check-linux": 1.3, "check-windows": 1.3, "check-postgres": MACOS_SLOW_HOST}


def test_each_nightly_suite_has_room_for_its_measured_length_and_is_still_a_hang_detector():
    """#1588: check-linux, check-windows and mutation (adopt) were cut at their limits every night 11-01..11-07."""
    doc, _ = _ci()
    for job, minutes in PROJECTED_JOB_MIN.items():
        limit = doc["jobs"][job]["timeout-minutes"]
        assert HOST_FACTOR[job] * minutes <= limit < 2 * minutes, (job, limit)


PG = "check-postgres"


def test_a_push_to_main_runs_on_postgres_only_what_it_reaches_and_the_nightly_runs_it_all():
    """#1584: push run 42412868007 ran the whole Postgres suite and was cut at 35 min."""
    doc, _ = _ci()
    job = doc["jobs"][PG]
    expr = job["env"][FAST]
    assert "github.event_name == 'push'" in expr and "github.event_name == 'pull_request'" in expr
    assert "schedule" not in expr and "workflow_dispatch" not in expr
    assert expr.replace(" ", "").endswith("&&'1'||'0'}}")
    select = next(s for s in job["steps"] if "tests.gauntlet.scope" in s.get("run", ""))
    assert select["if"] == f"env.{FAST} == '1'"
    assert '--base "$BASE"' in select["run"] and "--map" in select["run"]
    base = select["env"]["BASE"]
    assert "github.event.before" in base and "format('origin/{0}', github.base_ref)" in base
    assert base == doc["jobs"]["store-touched"]["steps"][1]["env"]["BASE"], "one base for what reaches the store and what runs"
    assert job["permissions"]["actions"] == "read", "the coverage map is an artifact"


RERUN = CI.parent / "rerun-cancelled.yml"


def test_a_cancelled_main_run_reruns_once_from_a_workflow_that_runs_after_it():
    """A run cannot rerun itself while in progress; workflow_run fires when the check run completes (#1520)."""
    doc = yaml.safe_load(RERUN.read_text(encoding="utf-8"))
    on = doc.get("on", doc.get(True))
    assert on["workflow_run"]["workflows"] == [yaml.safe_load(CI.read_text(encoding="utf-8"))["name"]]
    assert on["workflow_run"]["types"] == ["completed"]
    (job,) = doc["jobs"].values()
    cond = " ".join(job["if"].split())
    for part in ("github.event.workflow_run.event == 'push'", "github.event.workflow_run.head_branch == 'main'",
                 "github.event.workflow_run.conclusion == 'cancelled'", "github.event.workflow_run.run_attempt <= 1"):
        assert part in cond, part
    assert job["permissions"] == {"contents": "read", "actions": "write", "pull-requests": "read"}
    run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "harness/ci_rerun.py" in run and "github.event.workflow_run.id" in run


def test_the_rerun_bound_in_the_workflow_is_the_registered_one():
    from harness import ci_rerun
    doc = yaml.safe_load(RERUN.read_text(encoding="utf-8"))
    (job,) = doc["jobs"].values()
    assert f"run_attempt <= {ci_rerun.RERUNS}" in " ".join(job["if"].split())


def test_a_cancelled_runs_report_is_given_the_moment_it_ended():
    doc, _ = _ci()
    report = next(s for s in doc["jobs"]["check-macos"]["steps"] if "harness.suite_time" in s.get("run", ""))
    assert '--now "$(date +%s)"' in report["run"]


FAST = "SOHOT_FAST_PATH"


def test_only_an_unlabelled_pull_request_takes_the_fast_path_on_macos():
    """push to main, schedule, dispatch and full-ci run the `long` tests too (#720)."""
    doc, _ = _ci()
    expr = doc["jobs"]["check-macos"]["env"][FAST]
    assert "github.event_name == 'pull_request'" in expr
    assert f"!contains(github.event.pull_request.labels.*.name, '{LABEL}')" in expr
    assert expr.replace(" ", "").endswith("&&'1'||'0'}}")
    for job in DEFERRED:
        assert FAST not in str(doc["jobs"][job])


def test_the_fast_path_variable_is_the_one_conftest_reads():
    from tests import conftest
    assert conftest.FAST_PATH_ENV == FAST


def test_make_check_spreads_the_suite_over_every_core():
    make = (CI.parents[2] / "Makefile").read_text(encoding="utf-8")
    recipe = make.split("\ntest:", 1)[1].split("\n\n", 1)[0]
    assert "pytest" in recipe and "-n $(PYTEST_N)" in recipe
    assert re.search(r"^PYTEST_N \?= auto$", make, re.M)


def test_every_parallel_pytest_in_the_makefile_takes_its_workers_from_pytest_n():
    """Agents told to run make check got 30 workers each from a hardcoded -n auto (#1722)."""
    make = (CI.parents[2] / "Makefile").read_text(encoding="utf-8").replace("\\\n", " ")
    runs = [line for line in make.splitlines() if re.search(r"\bpytest\b", line) and not line.lstrip().startswith("#")]
    workers = [re.findall(r"(?<!\S)(?:-n|--numprocesses)(?:[ =]|(?=\w))(\S+)", line) for line in runs]
    assert sum(map(len, workers)) >= 2
    assert {w for ws in workers for w in ws} == {"$(PYTEST_N)"}


def test_check_macos_reports_where_the_test_time_went():
    doc, _ = _ci()
    steps = doc["jobs"]["check-macos"]["steps"]
    check = next(s for s in steps if s.get("name") == "make check")
    assert "--junitxml=/tmp/junit.xml" in check["env"]["PYTEST_ADDOPTS"]
    assert check["env"]["SOHOT_TEST_LOG"] == "/tmp/test-times.tsv"
    report = next(s for s in steps if "harness.suite_time" in s.get("run", ""))
    assert report.get("if") == "always()" and "/tmp/junit.xml" in report["run"]
    assert "--log /tmp/test-times.tsv" in report["run"] and "--against /tmp/prev/junit.xml" in report["run"]
    assert "gh run download" in report["run"] and "-n junit-macos -D /tmp/prev" in report["run"]
    assert doc["jobs"]["check-macos"]["permissions"]["actions"] == "read"


def test_the_test_log_variable_is_the_one_conftest_reads():
    from tests import conftest
    doc, _ = _ci()
    check = next(s for s in doc["jobs"]["check-macos"]["steps"] if s.get("name") == "make check")
    assert conftest.TEST_LOG_ENV in check["env"]


def test_a_hung_test_names_itself_before_the_job_timeout():
    """A stack dump per hung test, well under the job timeout and over the slowest real test (#712)."""
    from tests import conftest
    doc, _ = _ci()
    job_s = doc["jobs"]["check-macos"]["timeout-minutes"] * 60
    assert 60 <= conftest.HANG_DUMP_S < job_s / 4
    assert 2 * conftest.HANG_DUMP_S <= conftest.HANG_EXIT_S < job_s / 3


def test_faulthandler_never_dumps_on_a_timer():
    """Its timed dump of a running thread spun forever in dump_frame and held check-macos to the job timeout (#1351)."""
    import tomllib
    ini = tomllib.loads((CI.parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    assert float(ini["tool"]["pytest"]["ini_options"].get("faulthandler_timeout", 0)) == 0
    for f in (CI, CI.parents[2] / "Makefile"):
        assert "faulthandler_timeout" not in f.read_text(encoding="utf-8")


def test_the_nightly_runs_the_litellm_suite_after_make_check():
    """No job ran make test-litellm, so a collection error under the litellm overlay went unseen (#1221)."""
    doc, _ = _ci()
    steps = doc["jobs"]["check-linux"]["steps"]
    check = _linux_step(steps, lambda s: "make check" in s.get("run", ""))
    litellm = _linux_step(steps, lambda s: "make test-litellm" in s.get("run", ""))
    assert litellm > check and steps[litellm].get("timeout-minutes")


def _cancels(value, event: str) -> bool:
    if isinstance(value, bool):
        return value
    m = re.fullmatch(r"\$\{\{\s*github\.event_name\s*(==|!=)\s*'(\w+)'\s*\}\}", str(value).strip())
    assert m, f"cancel-in-progress {value!r} is not a form this test can evaluate"
    return (event == m.group(2)) == (m.group(1) == "==")


def test_a_push_to_main_is_never_cancelled_by_the_next_merge():
    """Merges faster than check-macos cancelled every main run, so no main sha went green and deploys starved (#1702)."""
    doc, _ = _ci()
    value = doc["concurrency"]["cancel-in-progress"]
    assert not _cancels(value, "push") and not _cancels(value, "schedule")
    assert _cancels(value, "pull_request")


def _expand(text: str, **github) -> str:
    """Evaluate each ${{ }} in text over a github context; && || == != and literals only."""
    def one(m):
        expr = re.sub(r"\bgithub\.(\w+)", lambda g: repr(github[g.group(1)]), m.group(1))
        expr = expr.replace("&&", " and ").replace("||", " or ")
        assert re.fullmatch(r"[\s\w'./=!-]*", expr), expr
        return str(eval(expr, {"__builtins__": {}}, {}))
    return re.sub(r"\$\{\{(.*?)\}\}", one, str(text))


def _group(event: str, ref: str, sha: str) -> str:
    doc, _ = _ci()
    return _expand(doc["concurrency"]["group"], event_name=event, ref=ref, sha=sha)


def test_a_merge_never_waits_for_the_previous_main_run():
    """One push group held each merge's run until the last one's check-postgres finished, and a newer pending run
    cancelled the older before it started; c200928b had no job 40 min after its merge (#1802)."""
    main = "refs/heads/main"
    assert _group("push", main, "a" * 40) != _group("push", main, "b" * 40)
    assert _group("push", main, "a" * 40) not in {_group(e, main, "a" * 40) for e in ("schedule", "workflow_dispatch")}
    assert _group("schedule", main, "a" * 40) == _group("schedule", main, "b" * 40)


def test_a_new_push_to_a_pull_request_cancels_its_superseded_run_only():
    doc, _ = _ci()
    pr = "refs/pull/1802/merge"
    assert _group("pull_request", pr, "a" * 40) == _group("pull_request", pr, "b" * 40)
    assert _group("pull_request", pr, "a" * 40) != _group("pull_request", "refs/pull/1801/merge", "a" * 40)
    assert _cancels(doc["concurrency"]["cancel-in-progress"], "pull_request")
    assert not _cancels(doc["concurrency"]["cancel-in-progress"], "push")


def test_no_job_joins_a_concurrency_group_of_its_own():
    """A job-level group would serialize main's check-macos across merges again (#1802)."""
    doc, _ = _ci()
    assert [n for n, j in doc["jobs"].items() if "concurrency" in j] == []


def test_mutation_never_runs_in_a_push_run_and_leaves_macos_runners_for_check_macos():
    """GitHub hands its 5 macOS runners to the oldest queued job: the 13:49 nightly's queued legs went ahead of the
    13:57 main check-macos for 55+ min. A leg held back by max-parallel is not queued yet (#1802)."""
    doc, _ = _ci()
    mutation = doc["jobs"]["mutation"]
    assert _expand("${{ " + mutation["if"] + " }}", event_name="push") == "False"
    assert _expand("${{ " + doc["jobs"]["mutation-plan"]["if"] + " }}", event_name="push") == "False"
    assert 1 <= mutation["strategy"]["max-parallel"] <= 2


def test_the_nightly_is_not_scheduled_on_the_hour():
    """'0 6 * * *' started 11:54-15:39 UTC on 2026-10-28..11-11, among the day's merges (#1802)."""
    _, on = _ci()
    assert all(c["cron"].split()[0] != "0" for c in on["schedule"])
