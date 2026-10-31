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
def test_a_pytest_run_past_its_timeout_is_killed_and_the_task_dropped(tmp_path, monkeypatch):
    slow = ADD_TEST + "\nimport time\ndef test_slow():\n    time.sleep(60)\n"
    ran = []
    real = history._pytest
    monkeypatch.setattr(history, "_pytest", lambda *a, **k: ran.append(1) or real(*a, **k))
    got = _survey(_repo(tmp_path, FIXED, slow), tmp_path, timeout=3)
    assert got["dropped"] == {"timeout": 1}
    # The first timeout drops the task; repeating it cost RUNS more timeouts on each side (#1146).
    assert len(ran) == 1


@DARWIN
def test_an_issue_with_no_solution_section_keeps_its_spec_variant_and_drops_only_the_symptom(tmp_path):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    got = history.survey(str(src), "main", 20, tmp_path / "log.txt",
                         get_issue=lambda n: {"title": "t", "body": "## Problem\nbroken\n"}, env=_here)
    (task,) = got["tasks"]
    assert got["dropped"] == {} and task["variant_drops"] == {"symptom": "no_fix_section"}
    assert task["prompts"]["symptom"] is None and task["prompts"]["spec"]
    assert [r["variant"] for r in history.fetch_rows(got)] == ["spec"]
    assert "cases: 1; symptom dropped on 1 tasks (no_fix_section)" in history.yield_table(got, dropped={})


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
    assert len(tasks) >= 12
    assert len({t["id"] for t in tasks}) == len(tasks)
    assert got["examined"] == len(tasks) + sum(got["dropped"].values()) == len(tasks) + len(got["drops"])
    for t in tasks:
        assert t["fail_to_pass"] and not set(t["fail_to_pass"]) & set(t["pass_to_pass"])
        assert {"files", "lines", "test_s", "area"} <= set(t["strata"])
        assert len(t["context_files"]) <= history.MAX_SOURCE_FILES
        assert (t["prompts"]["symptom"] and t["prompts"]["symptom"] != t["prompts"]["spec"]
                or t["variant_drops"] == {"symptom": "no_fix_section"})


def test_the_committed_manifest_converts_to_both_variants_of_every_task():
    rows = history.fetch()
    cases = [history.convert(r).case for r in rows]
    variants = {f"{t['id']}-{v}" for t in history.manifest()["tasks"] for v in history.VARIANTS if t["prompts"].get(v)}
    assert set(history.DROPPED) <= variants
    assert len(cases) == len(variants) - len(history.DROPPED) - len(set(history.RETIRED) & variants)
    for c in cases:
        assert set(c["params"]) - {"new_files", "interface", "stated"} == PARAMS and len(c["params"]["base"]) == 40
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


# --- growing the set (#997) -----------------------------------------------------------

#: The pilot's tasks as #996 froze them: fix sha, split side and a digest of the whole row. A grown manifest keeps every one.
PILOT = {
    "sohot-363": ("bf4586bc2951", "holdout", "0055d7accb2b"),
    "sohot-368": ("5839a3552153", "dev", "2dc141b03b71"),
    "sohot-371": ("467550a8e0da", "holdout", "da55fcb8daf7"),
    "sohot-374": ("fee4061ce915", "holdout", "9d282e786206"),  # prompt reworded to drop a private name, #1308
    "sohot-376": ("67dc663cb680", "dev", "d5bb2cdc5c39"),
    "sohot-396": ("8f2219efa0bf", "holdout", "c60c3b145556"),
    "sohot-399": ("7d44a19c8fc4", "holdout", "be97c54bf9e5"),
    "sohot-404": ("73432117367a", "dev", "b32fc66a8bdc"),
    "sohot-438": ("295ba9e5b47a", "holdout", "e6ca767b4c68"),
    "sohot-455": ("93b0d696963a", "holdout", "58711bdce933"),
    "sohot-570": ("fd1698fba9aa", "dev", "bf663ad10268"),
    "sohot-598": ("6fcaf37ed54e", "holdout", "b3aa3cfe3650"),
    "sohot-632": ("5068697ae0ec", "dev", "6fa1af686307"),
    "sohot-642": ("50a5aba1dfff", "holdout", "2907a5182b1e"),
    "sohot-647": ("29cad057045f", "holdout", "85e294997b95"),
    "sohot-720": ("78b0d43faa3c", "dev", "6d5e2666318d"),
    "sohot-788": ("9f042f9d5230", "holdout", "7065a769beae"),
    "sohot-858": ("df54638acb63", "dev", "0f3b2deeb33c"),
    "sohot-859": ("8ae08a76bd29", "holdout", "75792e5f3aba"),
    "sohot-879": ("9382f449fa0e", "holdout", "53069d376a4b"),
}


def _row_digest(task) -> str:
    import hashlib
    import json
    # interface is derived from the fix commit (#1103); the rest of the row must not move.
    rest = {k: v for k, v in task.items() if k not in ("interface", "unlisted")}
    return hashlib.sha256(json.dumps(rest, sort_keys=True).encode()).hexdigest()[:12]


def test_the_pilot_tasks_keep_their_ids_fix_commits_rows_and_split_sides():
    m = history.manifest()
    tasks = {t["id"]: t for t in m["tasks"]}
    sides = {i: s for s in ("dev", "holdout") for i in m["split"][s]}
    for tid, (fix, side, digest) in PILOT.items():
        assert tid in tasks, f"{tid} left the manifest"
        assert tasks[tid]["fix"].startswith(fix) and sides[tid] == side == history.side_of(tasks[tid]["fix"])
        assert _row_digest(tasks[tid]) == digest, f"{tid}'s row changed"


def _mul(src):
    _commit(src, {"mod.py": FIXED + "\ndef mul(a, b):\n    return a * b\n",
                  "tests/test_mul.py": "import mod\n\ndef test_mul():\n    assert mod.mul(2, 3) == 6\n"},
            "mul multiplies (#7) (#8)")


def _old(src) -> dict:
    """A manifest holding the fixture's #5 fix as an already surveyed task, with a row no survey would write."""
    fix, base = subprocess.run(["git", "-C", str(src), "rev-parse", "main", "main^"],
                               capture_output=True, text=True).stdout.split()
    return {"revision": fix, "tasks": [{"id": "sohot-5", "issue": 5, "pr": 6, "fix": fix, "base": base,
                                       "prompts": {"spec": "kept as written", "symptom": "s"}}]}


def test_growing_keeps_an_old_task_as_it_was_and_fetches_the_commits_since(tmp_path):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    keep = _old(src)
    history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: None,
                   env=lambda task: pytest.fail("nothing runs"), keep=keep)
    _mul(src)
    asked = []
    got = history.survey(str(src), "main", None, tmp_path / "log.txt",
                         get_issue=lambda n: asked.append(n) or ISSUE,
                         env=lambda task: pytest.fail("nothing runs"), keep=keep, run=False)
    assert got["tasks"] == keep["tasks"] and asked == [7] and got["drops"] == []
    assert got["candidates"] == 2 and [p["issue"] for p in got["pending"]] == [7]
    assert got["split"] == history.split(keep["tasks"]) and got["criteria"]["kept_from"] == keep["revision"]


def test_a_newer_fix_for_an_old_tasks_issue_is_a_duplicate_and_the_old_task_stays(tmp_path):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    keep = _old(src)
    _commit(src, {"mod.py": FIXED + "\n", "tests/test_mod.py": ADD_TEST + "\n"}, "add again (#5) (#9)")
    got = history.survey(str(src), "main", None, tmp_path / "log.txt",
                         get_issue=lambda n: pytest.fail("no issue is read"),
                         env=lambda task: pytest.fail("nothing runs"), keep=keep)
    assert got["tasks"] == keep["tasks"] and got["dropped"] == {"duplicate_issue": 1}


def test_a_kept_task_the_revision_does_not_hold_stops_the_survey(tmp_path):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    keep = {"tasks": [{"id": "sohot-1", "issue": 1, "fix": "e" * 40}]}
    with pytest.raises(RuntimeError, match="sohot-1"):
        history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: None, keep=keep)


@DARWIN
def test_a_grown_task_is_probed_and_takes_the_side_its_fix_draws(tmp_path):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    keep = _old(src)
    _mul(src)
    got = _survey(src, tmp_path, keep=keep)
    new = next(t for t in got["tasks"] if t["id"] == "sohot-7")
    assert new["fail_to_pass"] == ["tests/test_mul.py::test_mul"] and got["tasks"][1:] == keep["tasks"]
    assert new["strata"]["size"] == "small" and "variant_drops" not in new
    assert new["id"] in got["split"][history.side_of(new["fix"])]


def test_the_yield_counts_every_candidate_once_with_post_survey_drops_and_the_unexamined():
    got = {"candidates": 10, "examined": 7, "criteria": {"limit": 3, "probes": None},
           "tasks": [{"id": f"sohot-{i}", "fix": c * 40, "prompts": {"spec": "p", "symptom": "q"},
                      "strata": {"files": 1, "lines": 9}} for i, c in ((1, "a"), (2, "b"), (3, "c"))],
           "dropped": {"too_big": 3, "flaky": 1}}
    lines = history.yield_table(got, dropped={"sohot-2-spec": "x", "sohot-2-symptom": "x", "sohot-3-spec": "x"})
    assert lines[0] == "10 candidates, 2 tasks, 5 dropped, 3 not examined (limit 3, probes None)"
    assert lines[1:4] == ["     3  too_big", "     1  flaky", "     1  validation"]
    assert lines[-1].startswith("split: ") and "2 tasks" not in lines[-1]


def test_the_committed_manifest_yield_adds_up():
    m = history.manifest()
    head = history.yield_table(m)[0]
    pool, usable, dropped = (int(w) for w in head.replace(",", "").split()[0:6:2])
    gone = sum(all(f"{t['id']}-{v}" in history.DROPPED for v in history.VARIANTS) for t in m["tasks"])
    assert usable == len(m["tasks"]) - gone and pool == m.get("candidates", m["examined"])
    assert pool >= usable + dropped


def test_an_issue_lookup_that_fails_raises_and_only_a_missing_issue_is_none(monkeypatch):
    def gh(rc, err):
        return lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout="", stderr=err)
    monkeypatch.setattr(history.subprocess, "run", gh(1, "GraphQL: Could not resolve to an issue or pull "
                                                         "request with the number of 9. (repository.issue)"))
    assert history.issue(9) is None
    monkeypatch.setattr(history.subprocess, "run", gh(1, "error connecting to api.github.com"))
    with pytest.raises(RuntimeError, match="api.github.com"):
        history.issue(9)


def test_a_dry_run_stops_after_its_probes_and_counts_the_rest_unexamined(tmp_path):
    src = _repo(tmp_path, FIXED, ADD_TEST)
    _mul(src)
    got = history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: ISSUE,
                         env=lambda task: pytest.fail("nothing runs"), probes=0)
    assert got["candidates"] == 2 and got["examined"] == 0 and got["tasks"] == []
    assert "2 not examined" in history.yield_table(got, dropped={})[0]


def test_a_survey_from_the_command_line_keeps_the_committed_tasks_unless_told_to_restart(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(history, "survey", lambda *a, keep=None, **kw: seen.append(keep) or
                        {**history.manifest(), "candidates": 1})
    for extra in ([], ["--restart"]):
        assert history.main(["--log", str(tmp_path / "l"), "--out", str(tmp_path / "m.json"), *extra]) == 0
    assert seen == [history.manifest(), None]


def test_the_size_stratum_is_the_pilot_cap_and_the_survey_takes_fixes_up_to_the_raised_one():
    assert history.size_of({"files": 3, "lines": 150}) == "small"
    assert history.size_of({"files": 4, "lines": 10}) == history.size_of({"files": 1, "lines": 151}) == "large"
    c = {"test_files": ["tests/test_x.py"], "source_files": [f"m{i}.py" for i in range(8)],
         "context_files": ["m0.py"], "lines": 400}
    assert history.screen(c) is None
    assert history.screen({**c, "lines": 401}) == history.screen({**c, "source_files": c["source_files"] + ["z.py"]}) == "too_big"


def test_a_run_cut_to_a_size_keeps_only_that_strata_of_history_tasks(monkeypatch):
    from types import SimpleNamespace

    from evals import run
    got = {"tasks": [{"fix": "a" * 40, "strata": {"files": 1, "lines": 5}},
                     {"fix": "b" * 40, "strata": {"files": 6, "lines": 300}}]}
    monkeypatch.setattr(history, "manifest", lambda path=history.MANIFEST: got)
    cases = [SimpleNamespace(id=f"{x}-spec", params={"fix": x * 40, "variant": "spec"}) for x in "ab"] + \
        [SimpleNamespace(id="hand", params={})]
    args = SimpleNamespace(size="large", modality="repo")
    assert [c.id for c in run.sized(cases, args)] == ["b-spec"]
    assert [c.id for c in run.sized(cases, SimpleNamespace(size="small", modality="repo"))] == ["a-spec"]
    assert run.sized(cases, SimpleNamespace(size="all", modality="repo")) == cases
    assert run.parse_args(["--modality", "repo", "--size", "small"]).size == "small"
    with pytest.raises(SystemExit):
        run.sized(cases[2:], args)
