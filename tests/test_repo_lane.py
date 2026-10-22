"""The repo lane: restore a commit, take one diff, grade it sandboxed with hidden tests. #887."""
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from evals import core, repo
from evals.core import Case, load_cases
from evals.runners.repo import RepoRunner
from harness import reasons

ROOT = Path(__file__).resolve().parents[1]
DARWIN = pytest.mark.skipif(sys.platform != "darwin" or not Path(repo.SANDBOX_EXEC).is_file(),
                            reason="grading runs under macOS sandbox-exec")

BUGGY = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
BASE_TESTS = "from pkg.mod import sub\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n"
HIDDEN = BASE_TESTS + "\n\ndef test_add_hidden_marker():\n    from pkg.mod import add\n    assert add(2, 2) == 4\n"


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                   capture_output=True)


def _sha(cwd, rev="HEAD"):
    return subprocess.run(["git", "rev-parse", rev], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def _two_commits(src, base: dict, fix: dict, **params) -> Case:
    """A repository whose base commit holds `base` and whose fix commit then writes `fix`; a repo Case on it."""
    _git(src.parent, "init", "-q", "-b", "main", str(src))
    for files in (base, fix):
        for rel, text in files.items():
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text(text, encoding="utf-8")
        _git(src, "add", "-A")
        _git(src, "commit", "-qm", "base" if files is base else "fix")
        if files is base:
            first = _sha(src)
    params = {"source_repo": str(src), "base": first, "fix": _sha(src), "variant": "spec",
              "context": "oracle", "context_files": ["pkg/mod.py"],
              "fail_to_pass": ["tests/test_mod.py::test_add_hidden_marker"],
              "pass_to_pass": ["tests/test_mod.py::test_sub"], **params}
    return Case(id="fixture", modality="repo", prompt="add() subtracts; make it add.", params=params)


BASE_FILES = {"pkg/__init__.py": "", "pkg/mod.py": BUGGY, "tests/test_mod.py": BASE_TESTS,
              "pytest.ini": "[pytest]\npythonpath = .\n"}


@pytest.fixture
def upstream(tmp_path):
    """A two-commit repository: base has the bug, fix fixes it and adds the hidden test."""
    return _two_commits(tmp_path / "upstream", BASE_FILES,
                        {"pkg/mod.py": FIXED, "tests/test_mod.py": HIDDEN})


def _here(task):
    """The harness's own venv stands in for `uv sync`: it has pytest and needs no network."""
    return Path(sys.prefix)


def runner_with(reply, seen=None, env=_here):
    r = RepoRunner("http://unused", "fake")
    r.attempt = lambda params: repo.Attempt.open(params, env=env)

    def ask(case, template=None):
        if seen is not None:
            seen.append(case.prompt)
        return reply, {}
    r._ask = ask
    return r


def _diff(old: str, new: str, path="pkg/mod.py") -> str:
    import difflib
    lines = difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}")
    return f"diff --git a/{path} b/{path}\n" + "".join(lines)


def test_hidden_tests_never_appear_in_the_prompt(upstream):
    seen = []
    runner_with("no diff here", seen).run(upstream)
    assert seen and "def add(a, b)" in seen[0] and "pkg/mod.py" in seen[0]
    assert "test_add_hidden_marker" not in seen[0]
    assert "tests/test_mod.py" not in seen[0] and "assert sub(3, 1)" not in seen[0]


def test_an_unappliable_diff_is_invalid_patch(upstream):
    bad = _diff("def nothing():\n    pass\n", "def nothing():\n    return 1\n")
    row = runner_with(f"```diff\n{bad}```").run(upstream)
    assert not row.passed and row.failure_class == reasons.INVALID_PATCH
    assert row.metrics["patch_applied"] == 0 and row.metrics["resolved"] == 0
    assert reasons.CLASSES[reasons.INVALID_PATCH] == ("broken", reasons.CANDIDATE)


def test_a_diff_that_writes_outside_the_tree_is_refused_by_git(upstream, tmp_path):
    escape = tmp_path / "escaped.txt"
    rel = Path("..") / ".." / ".." / escape.name
    bad = (f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n"
           "@@ -0,0 +1 @@\n+owned\n")
    row = runner_with(bad).run(upstream)
    assert row.failure_class == reasons.INVALID_PATCH
    assert not list(tmp_path.rglob(escape.name))


def test_an_environment_failure_is_never_the_models(upstream):
    def broken(task):
        raise repo.RepoEnvError("uv sync --frozen failed: no network")
    row = runner_with("x", env=broken).run(upstream)
    assert row.failure_class == reasons.ENVIRONMENT_ERROR
    assert reasons.ENVIRONMENT_ERROR in reasons.NEVER_RAN


@pytest.mark.parametrize("source, stem", [
    ("C:\\Users\\runneradmin\\AppData\\Local\\Temp\\pytest-0\\test_x0\\upstream", "upstream"),
    ("https://github.com/org/proj.git", "proj"),
    ("/tmp/a/b/proj/", "proj"),
    ("/tmp/" + "x" * 200, "x" * 40),
])
def test_a_mirror_is_named_by_the_last_component_of_its_source(source, stem):
    """A whole Windows path kept as the name overran MAX_PATH in git clone. #897."""
    name = repo.mirror_path(source).name
    assert name.startswith(stem + "-") and len(name) <= 40 + 18


def test_an_attempt_leaves_no_checkout_behind(upstream):
    runner_with("no diff").run(upstream)
    work = repo.cache_root() / "work"
    assert not work.is_dir() or not list(work.iterdir())


@DARWIN
def test_the_profile_denies_a_socket_and_a_write_outside_the_task(tmp_path):
    task, outside = (tmp_path / "task").resolve(), (tmp_path / "outside").resolve()
    task.mkdir()
    outside.mkdir()
    probe = ("import socket, sys\n"
             "open(sys.argv[1] + '/in.txt', 'w').write('x')\n"
             "try:\n    open(sys.argv[2] + '/out.txt', 'w').write('x'); print('WROTE')\n"
             "except PermissionError: print('write denied')\n"
             "try:\n    socket.create_connection(('127.0.0.1', int(sys.argv[3])), 2); print('CONNECTED')\n"
             "except PermissionError: print('socket denied')\n")
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        rc, out, late = repo.run_sandboxed([sys.executable, "-c", probe, str(task), str(outside), str(port)],
                                           task, 60)
    assert (task / "in.txt").is_file() and not (outside / "out.txt").exists()
    assert "write denied" in out and "socket denied" in out, out
    assert rc == 0 and not late


@DARWIN
def test_model_code_that_escapes_or_dials_out_is_denied_while_tests_run(upstream, tmp_path):
    escape = (tmp_path / "escaped.txt").resolve()
    hits, misses = [], []
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)
    port = server.getsockname()[1]

    def accept():
        try:
            hits.append(server.accept())
        except OSError as exc:
            misses.append(exc)
    t = threading.Thread(target=accept)
    t.start()
    evil = FIXED + (f"\nopen({str(escape)!r}, 'w').write('owned')\n"
                    f"import socket\nsocket.create_connection(('127.0.0.1', {port}), 2)\n")
    row = runner_with(_diff(BUGGY, evil)).run(upstream)
    t.join()
    server.close()
    assert not escape.exists() and not hits and misses
    assert row.metrics["patch_applied"] == 1 and not row.passed


@DARWIN
def test_the_reference_diff_resolves_and_the_empty_one_does_not(upstream):
    assert repo.controls(upstream, env=_here)["verdict"] == "valid"
    row = runner_with(_diff(BUGGY, FIXED)).run(upstream)
    assert row.passed and row.metrics["resolved"] == 1 and row.metrics["patch_applied"] == 1
    assert row.seconds == row.metrics["wall_s"]


@DARWIN
def test_a_model_that_rewrites_the_tests_is_graded_on_the_real_ones(upstream):
    cheat = _diff(BASE_TESTS, "def test_add_hidden_marker():\n    assert True\n\n\ndef test_sub():\n"
                  "    assert True\n", path="tests/test_mod.py")
    row = runner_with(cheat).run(upstream)
    assert row.metrics["patch_applied"] == 1 and not row.passed
    assert "test_add_hidden_marker" in row.detail


@DARWIN
def test_tests_skipped_by_model_code_do_not_resolve_although_pytest_exits_0(upstream):
    skip = FIXED + "\nimport pytest\npytest.skip('not today', allow_module_level=True)\n"
    row = runner_with(_diff(BUGGY, skip)).run(upstream)
    assert row.metrics["patch_applied"] == 1 and not row.passed
    assert "fail_to_pass still failing" in row.detail


@DARWIN
def test_model_code_that_exits_0_before_the_tests_run_does_not_resolve(upstream):
    quit_early = FIXED.replace("return a + b", "return a - b") + "\nimport os\nos._exit(0)\n"
    row = runner_with(_diff(BUGGY, quit_early)).run(upstream)
    assert row.metrics["patch_applied"] == 1 and not row.passed
    assert "no report" in row.detail


@pytest.mark.parametrize("key,value,why", [
    ("base", "abc123", "40-hex"), ("variant", "other", "spec, symptom or request"),
    ("context_files", ["tests/test_mod.py"], "would show the model tests"),
    ("fail_to_pass", [], "fail_to_pass")])
def test_a_case_that_cannot_be_graded_is_refused_at_load(upstream, key, value, why):
    with pytest.raises(ValueError, match=why):
        repo.validate("x.yaml", {**upstream.params, key: value})


def test_the_commit_and_the_tests_are_in_the_digest(upstream):
    other = Case(**{**upstream.__dict__, "params": {**upstream.params, "fix": "f" * 40}})
    assert core.cases_digest([upstream]) != core.cases_digest([other])


def test_the_shipped_task_loads_with_both_commits_pinned():
    cases = load_cases(ROOT / "evals" / "cases" / "repo")
    assert cases and all(c.modality == "repo" for c in cases)
    for c in cases:
        repo.validate(c.id, c.params)


@DARWIN
def test_soh_cases_control_repo_reports_a_sound_task(upstream, tmp_path, monkeypatch, capsys):
    import yaml
    from harness import cli
    (tmp_path / "cases" / "repo").mkdir(parents=True)
    raw = {"id": "fixture", "modality": "repo", "prompt": upstream.prompt, "params": upstream.params}
    (tmp_path / "cases" / "repo" / "fixture.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setattr(repo, "prepare", _here)
    assert cli.main(["cases", "control", "repo", "--out", str(tmp_path / "cases")]) == 0
    assert "fixture: valid" in capsys.readouterr().out
    from harness import memory_store as ms
    case = load_cases(tmp_path / "cases" / "repo")[0]
    assert repo.verdicts([case], ms.this_machine()["fingerprint"]) == {"fixture": "valid"}


@DARWIN
def test_soh_cases_regrade_repo_grades_a_runs_stored_diffs_again(upstream, tmp_path, monkeypatch, capsys):
    import json
    import yaml
    from harness import cli
    (tmp_path / "cases" / "repo").mkdir(parents=True)
    raw = {"id": "fixture", "modality": "repo", "prompt": upstream.prompt, "params": upstream.params}
    (tmp_path / "cases" / "repo" / "fixture.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    headerless = (_diff(BUGGY, FIXED).split("\n", 1)[1]
                  + "--- /dev/null\n+++ b/pkg/extra.py\n@@ -0,0 +1 @@\n+X = 1\n")
    run = tmp_path / "run"
    run.mkdir()
    stored = {"case": "fixture", "diff": headerless, "grade": {"resolved": False, "patch_applied": False}}
    (run / "cand--fixture.json").write_text(json.dumps(stored), encoding="utf-8")
    before = (run / "cand--fixture.json").read_bytes()
    monkeypatch.setattr(repo, "prepare", _here)
    assert cli.main(["cases", "regrade", "repo", "--json", "--run", str(run),
                     "--out", str(tmp_path / "cases")]) == 0
    got = json.loads(capsys.readouterr().out)["regraded"]
    assert [(r["case"], r["was_resolved"], r["resolved"]) for r in got] == [("fixture", False, True)]
    assert (run / "cand--fixture.json").read_bytes() == before
    assert cli.main(["cases", "regrade", "repo", "--run", str(run), "--case", "other",
                     "--out", str(tmp_path / "cases")]) == 1


@DARWIN
def test_tests_that_outrun_the_timeout_are_our_limit_not_a_wrong_answer(upstream, monkeypatch):
    monkeypatch.setattr(repo, "TEST_TIMEOUT_S", 3.0)
    row = runner_with(_diff(BUGGY, FIXED + "\nimport time\ntime.sleep(60)\n")).run(upstream)
    assert (row.passed, row.failure_class, row.limit) == (False, reasons.TIMEOUT, "repo_test_timeout_s>3")


def test_install_tests_leaves_the_graders_own_directory_alone(upstream):
    p = upstream.params
    a = repo.Attempt.open(p, env=_here)
    try:
        kept = a.task / repo.HARNESS_DIR / "tmp" / "pytest-0" / "test_kept.py"
        kept.parent.mkdir(parents=True)
        kept.write_text("x", encoding="utf-8")
        repo.install_tests(a.mirror, a.task, p["base"], p["fix"])
        assert kept.read_text(encoding="utf-8") == "x"
    finally:
        a.close()


@DARWIN
def test_install_tests_is_idempotent_around_a_pytest_run(upstream):
    """#899: the second call met pytest's .grade/tmp/test_* dirs and raised EPERM."""
    p = dict(upstream.params)
    src = Path(p["source_repo"])
    # A nested repository is what makes git status list the test_* directory itself.
    uses_tmp = HIDDEN + ("\n\ndef test_writes_tmp(tmp_path):\n    import subprocess\n"
                         "    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)\n")
    (src / "tests" / "test_mod.py").write_text(uses_tmp, encoding="utf-8")
    _git(src, "commit", "-qam", "tmp")
    p["fix"] = _sha(src)
    a = repo.Attempt.open(p, env=_here)
    try:
        repo.install_tests(a.mirror, a.task, p["base"], p["fix"])
        g = repo.grade(a.task, a.python, ["tests/test_mod.py::test_writes_tmp"], [])
        assert g.resolved, g.detail
        assert list((a.task / repo.HARNESS_DIR / "tmp").rglob("test_writes_tmp*"))
        repo.install_tests(a.mirror, a.task, p["base"], p["fix"])
        assert (a.task / "tests" / "test_mod.py").read_text(encoding="utf-8") == uses_tmp
    finally:
        a.close()


def test_a_file_the_fix_creates_is_named_to_create_and_never_read_at_base(upstream):
    params = {**upstream.params, "new_files": ["pkg/helper.py"]}
    seen = []
    runner_with("no diff here", seen).run(Case(id="fixture", modality="repo",
                                               prompt=upstream.prompt, params=params))
    assert seen and "--- pkg/mod.py ---" in seen[0]
    assert "Files to create (they do not exist at the commit to fix): pkg/helper.py" in seen[0]


@pytest.mark.parametrize("new, why", [(["pkg/mod.py"], "both shown at base and created"),
                                      (["tests/test_new.py"], "would show the model tests")])
def test_a_new_file_that_is_also_shown_or_is_a_test_is_refused(upstream, new, why):
    with pytest.raises(ValueError, match=why):
        repo.validate("c", {**upstream.params, "new_files": new})


def test_a_hunk_that_misses_base_reports_plain_apply_and_not_the_3way_fallback(upstream):
    a = repo.Attempt.open(upstream.params, env=_here)
    try:
        got = a.submit(_diff("def add(a, b):\n    return a * b\n", "def add(a, b):\n    return a + b\n"))
    finally:
        a.close()
    assert not got.patch_applied and "patch does not apply" in got.detail
    assert "lacks the necessary blob" not in got.detail


def _planted(upstream, base=None, fix=None, **params) -> Case:
    """The upstream fixture rebuilt with some files or params changed, in a sibling repository."""
    src = Path(upstream.params["source_repo"]).with_name("planted")
    return _two_commits(src, {**BASE_FILES, **(base or {})},
                        {"pkg/mod.py": FIXED, "tests/test_mod.py": HIDDEN, **(fix or {})}, **params)


FLIP = ("\n\ndef test_flip():\n    import os, pathlib\n"
        "    f = pathlib.Path(os.environ['TMPDIR']) / 'flip'\n"
        "    if f.exists():\n        f.unlink()\n        assert False\n    f.write_text('x')\n")
EXIT_UNLESS_FIXED = "import os\nfrom pkg.mod import add\nif add(2, 2) != 4:\n    os._exit(0)\n"
H = "tests/test_mod.py::"
PLANTED = {
    "base equal to fix": (dict(base={"pkg/mod.py": FIXED}, fix={"pkg/mod.py": FIXED + "# fixed\n"}),
                          "invalid: fail_to_pass passes at base: " + H + "test_add_hidden_marker"),
    "an extra fail_to_pass already passes": (dict(fail_to_pass=[H + "test_add_hidden_marker", H + "test_sub"],
                                                  pass_to_pass=[]),
                                             "invalid: fail_to_pass passes at base: " + H + "test_sub (passed)"),
    "a pass_to_pass fails at base": (dict(fix={"tests/test_mod.py": HIDDEN + "\n\ndef test_add_zero():\n"
                                               "    from pkg.mod import add\n    assert add(0, 1) == 1\n"},
                                          pass_to_pass=[H + "test_sub", H + "test_add_zero"]),
                                     "invalid: pass_to_pass fails at base: " + H + "test_add_zero (failed)"),
    "the reference fails one id": (dict(fix={"tests/test_mod.py": HIDDEN + "\n\ndef test_never():\n"
                                             "    assert False\n"},
                                        pass_to_pass=[H + "test_sub", H + "test_never"]),
                                   "reference fails: " + H + "test_never (failed)"),
    "a conftest exits 0 at base": (dict(base={"conftest.py": EXIT_UNLESS_FIXED}),
                                   "error: base: pytest wrote no report (exit 0)"),
    "a test fails on alternate runs": (dict(base={"tests/test_mod.py": BASE_TESTS + FLIP},
                                            fix={"tests/test_mod.py": HIDDEN + FLIP},
                                            pass_to_pass=[H + "test_sub", H + "test_flip"]),
                                       "flaky: " + H + "test_flip"),
    "a context file is absent at base": (dict(fix={"pkg/new.py": "X = 1\n"},
                                              context_files=["pkg/mod.py", "pkg/new.py"]),
                                         "invalid: prompt: context file pkg/new.py is not in the base commit"),
}


@DARWIN
@pytest.mark.parametrize("name", sorted(PLANTED))
def test_a_planted_bad_case_is_rejected_with_its_reason(upstream, name):
    """Each passes the old aggregate control (or fails it without a reason); test by test it is named. #920."""
    edits, why = PLANTED[name]
    got = repo.controls(_planted(upstream, **edits), env=_here)
    assert why in got["verdict"] and got["verdict"] != "valid", got["verdict"]


@DARWIN
def test_a_sound_case_is_valid_with_every_id_recorded_per_run(upstream):
    got = repo.controls(upstream, env=_here)
    assert got["verdict"] == "valid", got["verdict"]
    assert len(got["base"]) == len(got["reference"]) == repo.VALIDATION_RUNS
    assert got["base"][0]["ids"] == {H + "test_add_hidden_marker": "failed", H + "test_sub": "passed"}
    assert set(got["reference"][-1]["ids"].values()) == {"passed"} and got["env_digest"]


def _runs(*outcomes, error=""):
    return [{"ids": dict(o), "error": error} for o in outcomes]


F2P, P2P = [H + "f"], [H + "p"]
OK_BASE = {H + "f": "failed", H + "p": "passed"}
OK_REF = {H + "f": "passed", H + "p": "passed"}


@pytest.mark.parametrize("base, ref, want", [
    (_runs(OK_BASE, OK_BASE), _runs(OK_REF, OK_REF), "valid"),
    (_runs(OK_BASE, error="tests timed out after 3s"), _runs(OK_REF), "error: base: tests timed out"),
    (_runs(OK_BASE), _runs(OK_REF, error="pytest wrote no report"), "error: reference: pytest wrote"),
    (_runs({H + "f": "error", H + "p": "error"}), _runs(OK_REF), "error: base: did not collect"),
    (_runs(OK_BASE, {**OK_BASE, H + "p": "failed"}), _runs(OK_REF), "flaky: " + H + "p"),
    (_runs(OK_BASE), _runs(OK_REF, {**OK_REF, H + "f": "failed"}), "flaky: " + H + "f"),
    (_runs({H + "f": "skipped", H + "p": "passed"}), _runs(OK_REF), "fail_to_pass does not run at base"),
    (_runs({H + "p": "passed"}), _runs(OK_REF), "valid"),  # an id parametrized on a name the fix adds
    (_runs({H + "f": "failed"}), _runs(OK_REF), "pass_to_pass fails at base: " + H + "p (missing)"),
    (_runs(OK_BASE), _runs({**OK_REF, H + "p": "skipped"}), "reference fails: " + H + "p (skipped)"),
])
def test_the_verdict_is_taken_test_by_test(base, ref, want):
    """The pure half of the control, so its logic runs on every platform. #920."""
    got = repo.verdict(base, ref, F2P, P2P)
    assert (got == want) if want == "valid" else (want in got), got


def test_a_verdict_is_this_machines_and_goes_stale_when_the_case_changes(upstream):
    got = {"verdict": "valid", "base": [], "reference": []}
    rec = repo.save_validation(upstream, got, "m1", "abc", 1.0)
    assert rec["cases_digest"] == core.cases_digest([upstream]) and rec["sohot_commit"] == "abc"
    repo.save_validation(upstream, {**got, "verdict": "flaky: x"}, "m2", "abc", 2.0)
    assert repo.verdicts([upstream], "m1") == {"fixture": "valid"}
    assert repo.verdicts([upstream], "m2") == {"fixture": "flaky: x"}
    assert repo.verdicts([upstream], "m3") == {"fixture": "unvalidated"}
    edited = Case(**{**upstream.__dict__, "prompt": "something else"})
    assert repo.verdicts([edited], "m1") == {"fixture": "stale"}


def test_a_repo_run_carries_each_cases_verdict_and_counts_valid_ones(upstream, tmp_path, monkeypatch, capsys):
    import json

    import yaml
    from evals import run
    from harness import memory_store as ms
    (tmp_path / "cases" / "repo").mkdir(parents=True)
    raw = {"id": "fixture", "modality": "repo", "prompt": upstream.prompt, "params": upstream.params}
    (tmp_path / "cases" / "repo" / "fixture.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    case = load_cases(tmp_path / "cases" / "repo")[0]
    repo.save_validation(case, {"verdict": "flaky: x"}, ms.this_machine()["fingerprint"], "c", 1.0)
    monkeypatch.setattr(run, "_repo_runner", lambda *a: runner_with("no diff here"))
    monkeypatch.setattr(run.env, "guard", lambda: None)
    run.main(["--modality", "repo", "--candidates", "fake", "--cases", str(tmp_path / "cases"),
              "--out", str(tmp_path / "out")])
    got = json.loads(next((tmp_path / "out").rglob("results.json")).read_text(encoding="utf-8"))
    assert got["receipt"]["validation"] == {"fixture": "flaky: x"}
    assert core.Receipt.from_dict(got["receipt"]).validation == {"fixture": "flaky: x"}
    out = capsys.readouterr().out
    assert "0 of 1 case(s) valid" in out and "not counted fixture: flaky: x" in out


def test_resolves_are_counted_over_valid_cases_only():
    from evals import run
    rows = [core.Result(case_id=c, candidate="m", passed=p, seconds=0.0, peak_kb=0, detail="") for c, p in
            (("a", True), ("b", True), ("c", False), ("a", False))]
    assert run.valid_only(rows, {"a": "valid", "b": "flaky: t", "c": "valid"}) == {"m": (1, 3)}
