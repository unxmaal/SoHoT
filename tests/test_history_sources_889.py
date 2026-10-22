"""The history importer over any repository: its commit shape, tracker, test command and environment are the source's. #889."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from evals import importers, repo
from evals.core import load_cases
from evals.importers import history

DARWIN = pytest.mark.skipif(sys.platform != "darwin" or not Path(repo.SANDBOX_EXEC).is_file(),
                            reason="the survey runs pytest under the lane's sandbox-exec")
ROOT = Path(__file__).resolve().parent.parent
ISSUE = {"title": "add subtracts", "body": "## Problem\nadd(2, 2) is 0.\n\n## Proposed fix\nUse +.\n"}
MERGES = history.Repo("merges", "m", "unused", "o/merges", "0" * 40, merges=True,
                      subject=re.compile(r"^Merge pull request #(?P<pr>\d+) from [^/\s]+/(?:[^/\s]+/)*(?P<issue>\d+)-"))
BROKEN = "def add(a, b):\n    return a - b\n\ndef sub(a, b):\n    return a - b\n"
FIXED = BROKEN.replace("a - b", "a + b", 1)
BASE_TEST = "from mod import add, sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n"
ADD_TEST = BASE_TEST + "\ndef test_add():\n    assert add(2, 2) == 4\n"


def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t",
                           "-c", "commit.gpgsign=false", *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(path, files: dict, subject: str):
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", subject)


def _merged(tmp_path, mod="mod.py", start=None) -> Path:
    """main: a start commit, a squash fix, then a fix merged from feat/7-add as GitHub writes it."""
    src = tmp_path / "src-repo"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _commit(src, start or {"pytest.ini": "[pytest]\npythonpath = .\n", mod: BROKEN,
                           "tests/test_mod.py": BASE_TEST}, "start")
    _commit(src, {"notes.txt": "x\n", "tests/test_notes.py": "def test_n():\n    pass\n"}, "notes (#3) (#4)")
    _git(src, "checkout", "-q", "-b", "feat/7-add")
    _commit(src, {mod: FIXED, "tests/test_mod.py": ADD_TEST}, "add adds")
    _git(src, "checkout", "-q", "main")
    _git(src, "merge", "-q", "--no-ff", "-m", "Merge pull request #8 from someone/feat/7-add", "feat/7-add")
    return src


def _here(task):
    return Path(sys.prefix)


def test_a_merge_source_takes_each_first_parent_merge_and_the_issue_its_branch_names(tmp_path):
    src = _merged(tmp_path)
    (c,) = history.candidates(src, "main", MERGES)
    assert (c["issue"], c["pr"]) == (7, 8)
    assert c["fix"] == _git(src, "rev-parse", "main") and c["base"] == _git(src, "rev-parse", "main^1")
    assert c["source_files"] == ["mod.py"] and c["test_files"] == ["tests/test_mod.py"] and c["lines"] == 2


def test_a_squash_source_ignores_merge_commits_and_a_merge_source_ignores_squashes(tmp_path):
    src = _merged(tmp_path)
    assert [(c["issue"], c["pr"]) for c in history.candidates(src, "main")] == [(3, 4)]
    assert all(c["issue"] != 3 for c in history.candidates(src, "main", MERGES))


def test_the_issue_is_read_from_the_sources_own_tracker(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(history, "issue", lambda n, tracker="": asked.append((n, tracker)) or ISSUE)
    got = history.survey(str(_merged(tmp_path)), "main", None, tmp_path / "log.txt", run=False, src=MERGES)
    assert asked == [(7, "o/merges")] and [p["issue"] for p in got["pending"]] == [7]
    assert got["source"] == "git:o/merges" and got["criteria"]["merges"] is True


def test_gh_is_asked_for_the_tracker_it_is_given(monkeypatch):
    seen = []

    class Done:
        returncode, stdout, stderr = 0, '{"title": "t", "body": ""}', ""

    monkeypatch.setattr(history.subprocess, "run", lambda argv, **kw: seen.append(argv) or Done())
    assert history.issue(5, "unxmaal/mcm-engine")["title"] == "t"
    assert seen[0][seen[0].index("-R") + 1] == "unxmaal/mcm-engine"


def test_a_prompt_naming_a_private_person_is_dropped_before_any_probe(tmp_path, monkeypatch):
    monkeypatch.setenv("LH_PRIVATE_NAMES", "Zebulon")
    body = {"title": "t", "body": "## Problem\nZebulon saw add(2, 2) give 0.\n"}
    got = history.survey(str(_merged(tmp_path)), "main", None, tmp_path / "log.txt", run=False, src=MERGES,
                         get_issue=lambda n: body)
    assert got["dropped"] == {"private_text": 1} and got["pending"] == []


def test_a_lan_address_or_mdns_host_reaches_the_prompt_as_a_placeholder():
    lan, mdns = "192." + "168.8.88", "studio" + ".local"
    got = history.prompts("t", f"## Problem\nhealthz on http://{lan}:8090 and {mdns} fails\n")
    assert lan not in got["spec"] and mdns not in got["spec"] and got["spec"].count("<host>") == 2
    assert history.private(got["spec"]) == []


def test_a_sources_own_solution_headings_leave_the_symptom_variant():
    body = "## Problem\nadd(2, 2) is 0.\n\n## Proposed fix\nUse +.\n"
    assert history.prompts("t", body)["symptom"] is None
    got = history.prompts("t", body, solution=("proposed fix",))
    assert "Use +." in got["spec"] and "Use +." not in got["symptom"] and "add(2, 2)" in got["symptom"]


def test_only_a_source_that_sets_a_test_command_or_extras_puts_them_in_its_cases():
    row = {"id": "x-1", "variant": "spec", "prompts": {"spec": "p"}, "base": "a" * 40, "fix": "b" * 40,
           "context_files": ["mod.py"], "fail_to_pass": ["t.py::a"], "pass_to_pass": [], "issue": 1, "pr": 2,
           "date": "2026-10-22"}
    plain = history.convert(row).case["params"]
    assert "pytest_args" not in plain and "extras" not in plain and plain["source_repo"] == history.REPO_URL
    src = history.Repo("s", "s", "https://example.invalid/s.git", "o/s", "c" * 40,
                       pytest_args=("-o", "pythonpath=src"), extras=("dev",))
    got = history.convert(row, src).case["params"]
    assert got["pytest_args"] == ["-o", "pythonpath=src"] and got["extras"] == ["dev"]
    assert got["source_repo"] == "https://example.invalid/s.git"
    repo.validate("x", got)


def test_a_case_whose_test_command_is_not_a_list_of_strings_is_refused():
    ok = {"source_repo": "s", "base": "a" * 40, "fix": "b" * 40, "fail_to_pass": ["t.py::a"],
          "context_files": ["m.py"], "variant": "spec", "context": "oracle"}
    repo.validate("x", ok)
    with pytest.raises(ValueError, match="pytest_args must be a list"):
        repo.validate("x", {**ok, "pytest_args": "-x"})
    with pytest.raises(ValueError, match="extras must be strings"):
        repo.validate("x", {**ok, "extras": [1]})


def test_extras_reach_uv_sync_and_key_their_own_environment(tmp_path, monkeypatch):
    task = tmp_path / "task"
    task.mkdir()
    (task / "uv.lock").write_text("lock\n", encoding="utf-8")
    assert repo.env_digest(task) == repo.env_digest(task, ()) != repo.env_digest(task, ("dev",))
    seen = []

    class Done:
        returncode, stderr = 0, ""

    def fake(argv, **kw):
        seen.append(argv)
        Path(kw["env"]["UV_PROJECT_ENVIRONMENT"]).mkdir(parents=True)
        return Done()

    monkeypatch.setattr(repo.subprocess, "run", fake)
    venv = repo.prepare(task, ("dev", "aaa"))
    assert venv.name == repo.env_digest(task, ("dev",  "aaa"))
    assert seen[0][-4:] == ["--extra", "aaa", "--extra", "dev"]


@DARWIN
def test_a_src_layout_source_is_surveyed_and_graded_through_its_own_test_command(tmp_path):
    start = {"src/mod.py": BROKEN, "tests/test_mod.py": BASE_TEST}
    src = _merged(tmp_path, mod="src/mod.py", start=start)
    bare = history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: ISSUE, env=_here,
                          src=MERGES)
    assert bare["tasks"] == [] and bare["dropped"] == {"reference_fails": 1}
    own = history.Repo("own", "own", str(src), "o/own", "0" * 40, subject=MERGES.subject, merges=True,
                       pytest_args=("-o", "pythonpath=src"), solution=("proposed fix",))
    got = history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: ISSUE, env=_here,
                         src=own)
    (task,) = got["tasks"]
    assert task["id"] == "own-7" and task["fail_to_pass"] == ["tests/test_mod.py::test_add"]
    assert task["prompts"]["symptom"] and "Use +." not in task["prompts"]["symptom"]
    params = history.convert({**task, "variant": "spec"}, own).case["params"]
    mirror = repo.mirror(str(src))
    for args, resolved in ((params["pytest_args"], True), ((), False)):
        t = repo.restore(mirror, task["base"])
        try:
            assert repo.apply(t, repo.reference_diff(mirror, task["base"], task["fix"]))[0]
            repo.install_tests(mirror, t, task["base"], task["fix"])
            got = repo.grade(t, repo.python_of(_here(t)), task["fail_to_pass"], task["pass_to_pass"], args)
            assert got.resolved is resolved, got.detail
        finally:
            repo.discard(mirror, t)
    from evals.core import Case
    case = Case(id="own-7-spec", modality="repo", prompt="p", params={**params, "source_repo": str(src)})
    assert repo.controls(case, env=_here, runs=1)["verdict"] == "valid"
    bare_case = Case(id="own-7-spec", modality="repo", prompt="p",
                     params={**params, "source_repo": str(src), "pytest_args": []})
    assert repo.controls(bare_case, env=_here, runs=1)["verdict"] != "valid"


def test_an_attempt_builds_its_environment_with_the_cases_extras(tmp_path, monkeypatch):
    src = _merged(tmp_path)
    asked = []
    monkeypatch.setattr(repo, "prepare", lambda task, extras=(): asked.append(tuple(extras)) or Path(sys.prefix))
    params = {"source_repo": str(src), "base": _git(src, "rev-parse", "main^1"), "fix": _git(src, "rev-parse", "main"),
              "extras": ["dev"]}
    repo.Attempt.open(params).close()
    repo.Attempt.open({**params, "extras": []}).close()
    assert asked == [("dev",), ()]
    monkeypatch.setattr(repo, "prepare", lambda task: Path(sys.prefix))
    repo.Attempt.open({**params, "extras": []}).close()


def test_every_registered_source_converts_its_manifest_at_its_revision_into_its_own_case_directory():
    srcs = history.repos()
    assert [r.name for r in srcs][:1] == ["history"] and len(srcs) >= 3
    assert len({r.prefix for r in srcs}) == len({r.url for r in srcs}) == len(srcs)
    for r in srcs:
        mod = importers.module(r.name)
        assert importers.Source(r.name, "repo") in importers.REGISTRY and mod.REPO is r
        rows = mod.fetch()
        assert rows and all(row["id"].startswith(f"{r.prefix}-") for row in rows)
        committed = {c.id for c in load_cases(ROOT / "evals" / "cases" / "repo" / r.name)}
        assert committed == {f"{row['id']}-{row['variant']}" for row in rows}
        assert {history.source_of(c.params) for c in load_cases(ROOT / "evals" / "cases" / "repo" / r.name)} == {
            r.prefix}


def test_the_yield_is_reported_per_source(capsys):
    assert history.main(["--yield"]) == 0
    out = capsys.readouterr().out
    for r in history.repos():
        assert f"{r.prefix} ({r.tracker}):" in out
    assert out.count(" candidates, ") == len(history.repos())


def test_the_repo_report_keeps_each_sources_tasks_in_a_block_of_their_own():
    from types import SimpleNamespace

    from evals import repo_report as R
    from evals.importers import history_mcm_engine
    urls = {"s": history.REPO_URL, "m": history_mcm_engine.REPO.url}
    cases = [SimpleNamespace(id=f"{k}{t}-{v}", params={"fix": f"{k}{t}".ljust(40, "0"), "variant": v,
                                                        "source_repo": url})
             for k, url in urls.items() for t in range(2 if k == "s" else 1) for v in history.VARIANTS]
    runs = [{"id": i, "lane": "repo", "repeat": 1, "cases_digest": "d", "receipt": {"modality": "repo"},
             "environment": {}, "generated_at": None} for i in (1, 2)]
    rows = [{"run_id": r, "candidate": c, "case_id": k.id, "repeat_index": 1, "passed": r == 2,
             "failure_class": "" if r == 2 else "wrong", "hit_limit": ""}
            for k in cases for r, c in ((1, "base"), (2, "cand"))]
    rep = R.report(runs, rows, cases, resamples=50, sizes={})
    assert {s: (v["tasks"], v["cases"]) for s, v in rep["sources"].items()} == {"sohot": (2, 4), "mcm-engine": (1, 2)}
    assert "limits as losses, mcm-engine tasks (source, #889): 2 cases from 1 tasks" in R.text(rep)


@DARWIN
def test_a_fix_whose_tests_do_not_collect_at_base_is_dropped_as_the_control_would_call_it(tmp_path):
    importing = "from mod import add, sub, mul\n" + ADD_TEST.split("\n", 1)[1] + "\ndef test_mul():\n    assert mul(2, 3) == 6\n"
    src = _merged(tmp_path)
    _git(src, "checkout", "-q", "-b", "feat/9-mul")
    _commit(src, {"mod.py": FIXED + "\ndef mul(a, b):\n    return a * b\n", "tests/test_mod.py": importing}, "mul")
    _git(src, "checkout", "-q", "main")
    _git(src, "merge", "-q", "--no-ff", "-m", "Merge pull request #10 from someone/feat/9-mul", "feat/9-mul")
    got = history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: ISSUE, env=_here,
                         src=MERGES)
    assert [t["issue"] for t in got["tasks"]] == [7] and got["dropped"] == {"base_error": 1}


def test_a_parametrize_id_holding_a_double_colon_maps_to_its_junit_key():
    assert repo.junit_key("tests/test_t.py::test_h[[::1]-[::1]:*]") == "tests.test_t::test_h[[::1]-[::1]:*]"
    assert repo.junit_key("tests/test_t.py::TestC::test_h[a::b]") == "tests.test_t.TestC::test_h[a::b]"
    assert repo.junit_key("tests/test_t.py::TestC::test_h") == "tests.test_t.TestC::test_h"
    keys = ["tests.test_t::test_h[[::1]-[::1]:*]"]
    assert [repo.junit_key(i) for i in history.node_ids(keys, ["tests/test_t.py"])] == keys
