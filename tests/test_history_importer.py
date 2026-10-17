"""The repo lane's historical task importer, on a fixture git repo built here; no network. #888."""
import subprocess
import sys
from pathlib import Path

import pytest

from evals import importers, repo
from evals.core import Case
from evals.importers import history

DARWIN = pytest.mark.skipif(sys.platform != "darwin" or not Path(repo.SANDBOX_EXEC).is_file(),
                            reason="the survey runs pytest under the lane's sandbox-exec")
PARAMS = {"source_repo", "base", "fix", "context_files", "fail_to_pass", "pass_to_pass",
          "variant", "context"}
ISSUE = {"title": "add subtracts", "body": "## Problem\nadd(2, 2) is 0.\n\n## Fix\nUse +.\n\n"
                                        "## Prior art checked\nnone\n"}

BASE_TEST = "from mod import add, sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n"
ADD_TEST = BASE_TEST + "\ndef test_add(tmp_path):\n    assert add(2, 2) == 4\n"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def _commit(repo, files: dict, subject: str):
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", subject)


def _repo(tmp_path, fixed: str, test: str, base_test: str = BASE_TEST) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, {"pytest.ini": "[pytest]\npythonpath = .\n",
                   "mod.py": "def add(a, b):\n    return a - b\n\ndef sub(a, b):\n    return a - b\n",
                   "tests/test_mod.py": base_test}, "start")
    _commit(repo, {"mod.py": fixed, "tests/test_mod.py": test}, "add adds (#5) (#6)")
    return repo


FIXED = "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n"


def _here(task):
    """The harness's own venv stands in for `uv sync`: it has pytest and needs no network."""
    return Path(sys.prefix)


def _survey(src, tmp_path, **kw):
    return history.survey(str(src), "main", 20, tmp_path / "log.txt", get_issue=lambda n: ISSUE,
                          env=_here, **kw)


@DARWIN
def test_a_flipping_test_becomes_one_task_with_its_fail_to_pass_and_pass_to_pass(tmp_path):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    got = _survey(src, tmp_path)
    assert got["dropped"] == {} and got["examined"] == 1
    (task,) = got["tasks"]
    assert task["fail_to_pass"] == ["tests/test_mod.py::test_add"]
    assert task["pass_to_pass"] == ["tests/test_mod.py::test_sub"]
    assert task["context_files"] == ["mod.py"] and task["issue"] == 5 and task["pr"] == 6
    assert task["strata"]["files"] == 1 and task["strata"]["lines"] == 2
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "main", "main^"],
                          capture_output=True, text=True).stdout.split()
    assert [task["fix"], task["base"]] == head
    work = repo.cache_root() / "work"
    assert not any(work.iterdir()), "the throwaway worktree is removed"


@DARWIN
def test_a_task_converts_to_a_spec_and_a_symptom_case_in_the_repo_lane_shape(tmp_path):
    got = _survey(_repo(tmp_path, FIXED, ADD_TEST), tmp_path)
    rows = [{**got["tasks"][0], "variant": v} for v in history.VARIANTS]
    cases = {c.case["params"]["variant"]: c.case for c in map(history.convert, rows)}
    assert set(cases) == {"spec", "symptom"}
    for v, case in cases.items():
        assert case["id"] == f"sohot-5-{v}" and case["modality"] == "repo"
        assert set(case["params"]) == PARAMS and case["params"]["context"] == "oracle"
        assert "Prior art" not in case["prompt"] and "add(2, 2) is 0." in case["prompt"]
    assert "Use +." in cases["spec"]["prompt"] and "Use +." not in cases["symptom"]["prompt"]


@DARWIN
def test_a_fix_whose_new_test_already_passes_at_base_is_dropped_since_the_empty_patch_resolves(tmp_path):
    passing = BASE_TEST + "\ndef test_more():\n    assert sub(5, 1) == 4\n"
    got = _survey(_repo(tmp_path, FIXED, passing), tmp_path)
    assert got["tasks"] == [] and got["dropped"] == {"no_flip": 1}


@DARWIN
def test_a_reference_that_fails_its_own_tests_is_dropped(tmp_path):
    got = _survey(_repo(tmp_path, FIXED.replace("a + b", "a * b + 1"), ADD_TEST), tmp_path)
    assert got["dropped"] == {"reference_fails": 1}


@DARWIN
def test_a_test_that_disagrees_with_itself_across_two_runs_is_dropped_as_flaky(tmp_path):
    flaky = ADD_TEST + ("\nimport pathlib\ndef test_once():\n    p = pathlib.Path('ran-once')\n"
                        "    seen = p.exists()\n    p.touch()\n    assert not seen\n")
    got = _survey(_repo(tmp_path, FIXED, flaky), tmp_path)
    assert got["dropped"] == {"flaky": 1}


@DARWIN
@pytest.mark.gauntlet("one-default-tuned-for-one-member-applied-to-all", site="evals/importers/history.py:outcomes(timeout)")
@pytest.mark.gauntlet("one-default-tuned-for-one-member-applied-to-all", site="evals/importers/history.py:probe(timeout)")
@pytest.mark.gauntlet("one-default-tuned-for-one-member-applied-to-all", site="evals/importers/history.py:survey(timeout)")
def test_a_pytest_run_past_its_timeout_is_killed_and_the_task_dropped(tmp_path):
    slow = ADD_TEST + "\nimport time\ndef test_slow():\n    time.sleep(60)\n"
    got = _survey(_repo(tmp_path, FIXED, slow), tmp_path, timeout=3)
    assert got["dropped"] == {"timeout": 1}


def test_an_issue_with_no_solution_section_is_dropped_before_anything_runs(tmp_path):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    got = history.survey(str(src), "main", 20, tmp_path / "log.txt",
                         get_issue=lambda n: {"title": "t", "body": "## Problem\nbroken\n"},
                         env=lambda task: pytest.fail("nothing runs"))
    assert got["dropped"] == {"no_fix_section": 1}


@DARWIN
def test_the_negative_control_resolves_the_reference_and_fails_the_empty_patch(tmp_path, monkeypatch):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    task = _survey(src, tmp_path)["tasks"][0]
    case = history.convert({**task, "variant": "spec"}).case
    monkeypatch.setattr(repo, "prepare", _here)
    c = Case(id=case["id"], modality="repo", prompt=case["prompt"],
             params={**case["params"], "source_repo": str(src)})
    got = importers.negative_control([c], history.RESPONDERS, history.passes)
    assert got == {"reference": (1, 1), "empty": (0, 1)}


def test_junit_keys_map_back_to_node_ids_through_the_files_run():
    keys = ["tests.test_a::test_x[1-2]", "tests.test_a.TestC::test_y", "tests.sub.test_b::test_z",
            "other::test_w"]
    files = ["tests/test_a.py", "tests/sub/test_b.py"]
    got = history.node_ids(keys, files)
    assert got == ["tests/sub/test_b.py::test_z", "tests/test_a.py::TestC::test_y",
                   "tests/test_a.py::test_x[1-2]"]
    assert all(repo.junit_key(i) in keys for i in got)


def test_symptom_strips_solution_sections_at_their_level_and_bold_labelled_paragraphs():
    body = ("## Problem\nit breaks\n### Seen\nerror X\n## Fix (two parts)\nchange y\n"
            "### Detail\nmore y\n## Done when\ntest passes\n\n**Shape:** do z\nstill z\n\n"
            "**Seen:** error W\n## Prior art checked\nKB #1\n")
    got = history.prompts("t", body)
    for kept in ("it breaks", "error X", "test passes", "error W"):
        assert kept in got["symptom"] and kept in got["spec"]
    for gone in ("change y", "more y", "do z", "still z"):
        assert gone not in got["symptom"] and gone in got["spec"]
    assert "KB #1" not in got["spec"]


def test_symptom_strips_plain_labelled_paragraphs_with_their_lists_and_keeps_what_follows():
    body = ("It fails with 400 for today.\n\nFix options:\n1. drop it\n\n2. keep it\n\n"
            "Done when: a test shows it.\n\nFix: request yesterday.\nAnd test it.\n\n"
            "Seen twice.\n\n**Fix:**\n\nchange w\n\nEvidence: log\n\nPrior art checked: #630 only.\n")
    got = history.prompts("t", body)
    for kept in ("400 for today", "Done when: a test", "Seen twice.", "Evidence: log"):
        assert kept in got["symptom"], kept
    for gone in ("drop it", "keep it", "request yesterday", "And test it", "change w"):
        assert gone not in got["symptom"] and gone in got["spec"], gone
    assert "#630" not in got["spec"]


def test_a_home_path_in_an_issue_reaches_the_prompt_as_a_tilde():
    got = history.prompts("t", "## Problem\nfails under " + "/Use" + "rs/someone/proj/deploy\n## Fix\nx\n")
    assert "/Users/" not in got["spec"] and "~/proj/deploy" in got["symptom"]


def test_a_lockfile_change_or_an_oversized_fix_is_screened_out():
    c = {"test_files": ["tests/test_a.py"], "source_files": ["harness/a.py"], "lines": 10,
         "context_files": ["harness/a.py"]}
    assert history.screen(c) is None
    assert history.screen({**c, "context_files": []}) == "only_new_files"
    assert history.screen({**c, "source_files": ["harness/a.py", "uv.lock"]}) == "dependency_change"
    assert history.screen({**c, "lines": history.MAX_LINES + 1}) == "too_big"
    assert history.screen({**c, "test_files": ["tests/fixtures/x.json"]}) == "no_test_change"


def test_the_importer_is_registered_in_the_repo_lane():
    assert importers.Source("history", "repo") in importers.REGISTRY


# --- the committed pilot manifest ------------------------------------------------------

def test_the_committed_manifest_is_pinned_versioned_and_a_pilot_sized_set_of_flipping_tasks():
    got = history.manifest()
    assert got["revision"] == history.REVISION and got["version"] == history.VERSION
    tasks = got["tasks"]
    assert 12 <= len(tasks) <= 20
    assert len({t["id"] for t in tasks}) == len(tasks)
    assert got["examined"] == len(tasks) + sum(got["dropped"].values()) == len(tasks) + len(got["drops"])
    for t in tasks:
        assert t["fail_to_pass"] and not set(t["fail_to_pass"]) & set(t["pass_to_pass"])
        assert {"files", "lines", "test_s", "area"} <= set(t["strata"])
        assert len(t["context_files"]) <= history.MAX_SOURCE_FILES
        assert t["prompts"]["symptom"] and t["prompts"]["symptom"] != t["prompts"]["spec"]


def test_the_committed_manifest_converts_to_both_variants_of_every_task():
    rows = history.fetch()
    cases = [history.convert(r).case for r in rows]
    assert len(cases) == 2 * len(history.manifest()["tasks"])
    for c in cases:
        assert set(c["params"]) - {"new_files"} == PARAMS and len(c["params"]["base"]) == 40
        assert c["prompt"].startswith("# ")



def _creating(tmp_path) -> Path:
    """A fix that edits mod.py and creates helper.py, which base does not have. #913."""
    src = _repo(tmp_path, FIXED, ADD_TEST)
    _git(src, "reset", "-q", "--hard", "HEAD^")
    _commit(src, {"mod.py": FIXED.replace("a + b", "plus(a, b)").replace(
        "def add", "from helper import plus\n\ndef add"), "helper.py": "def plus(a, b):\n    return a + b\n",
        "tests/test_mod.py": ADD_TEST}, "add adds (#5) (#6)")
    return src


def test_a_file_the_fix_creates_is_split_out_of_the_context_and_refresh_recomputes_it(tmp_path):
    src = _creating(tmp_path)
    (c,) = history.candidates(src, "main")
    assert c["source_files"] == ["helper.py", "mod.py"]
    assert c["context_files"] == ["mod.py"] and c["new_files"] == ["helper.py"]
    old = {"tasks": [{"id": "sohot-5", "base": c["base"], "fix": c["fix"],
                      "context_files": ["helper.py", "mod.py"]}]}
    (t,) = history.refresh(old, src)["tasks"]
    assert t["context_files"] == ["mod.py"] and t["new_files"] == ["helper.py"]


@DARWIN
def test_a_task_whose_fix_creates_a_file_names_it_to_create_and_its_reference_resolves(tmp_path):
    src = _creating(tmp_path)
    got = _survey(src, tmp_path)
    (task,) = got["tasks"]
    assert task["context_files"] == ["mod.py"] and task["new_files"] == ["helper.py"]
    case = history.convert({**task, "variant": "spec"}).case
    assert case["params"]["new_files"] == ["helper.py"]
    a = repo.Attempt.open({**case["params"], "source_repo": str(src)}, env=_here)
    try:
        asked = a.prompt(case["prompt"])
    finally:
        a.close()
    assert "--- mod.py ---" in asked and "--- helper.py ---" not in asked
    assert "Files to create (they do not exist at the commit to fix): helper.py" in asked
