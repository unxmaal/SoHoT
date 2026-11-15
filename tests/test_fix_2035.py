"""soh fix (#2035): the runner's gate refuses a test edit, an unplanned file and a test that passes at base."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness import fix

PYTEST = (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider")
TEST = "tests/test_mod_1.py"
FAILING = "from pkg.mod import f\n\n\ndef test_f():\n    assert f() == 2\n"


def _git(ws: Path, *args) -> None:
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=ws, check=True,
                   capture_output=True)


@pytest.fixture
def ws(tmp_path) -> Path:
    w = tmp_path / "ws"
    (w / "pkg").mkdir(parents=True)
    (w / "pkg" / "mod.py").write_text("def f():\n    return 1\n")
    (w / "pkg" / "other.py").write_text("X = 1\n")
    (w / "tests").mkdir()
    (w / "tests" / "test_other.py").write_text("from pkg.mod import f\n\n\ndef test_int():\n    assert isinstance(f(), int)\n")
    (w / ".gitignore").write_text("__pycache__/\n")
    _git(w, "init", "-q")
    _git(w, "add", ".gitignore", "pkg", "tests")
    _git(w, "commit", "-qm", "base")
    return w


def _plan(test_code: str = FAILING, files=("pkg/mod.py",), klass: str = "read_the_field") -> dict:
    return {"class": klass, "why": "", "files": list(files), "test_path": TEST, "test_code": test_code,
            "brief": "make f return 2"}


def _planner(plan: dict, tokens=None):
    calls = []

    def plan_fn(prompt, ws):
        calls.append(prompt)
        return {"text": json.dumps(plan), "tokens": tokens or {"input": 1000, "output": 500, "cache_write": 2000,
                                                                "cache_read": 9000}}
    plan_fn.calls = calls
    return plan_fn


def _executor(*edits):
    """A fake local step: each attempt applies the next edit to the workspace."""
    prompts = []

    def execute(ws, prompt, call_id):
        prompts.append(prompt)
        edits[min(len(prompts), len(edits)) - 1](ws)
        return {"exit": 0, "turns": 3, "tokens": {"input": 40000, "output": 2000}}
    execute.prompts = prompts
    return execute


def fixes(ws):
    (ws / "pkg" / "mod.py").write_text("def f():\n    return 2\n")


def edits_the_test(ws):
    (ws / TEST).write_text(FAILING.replace("== 2", "== 1"))


def touches_unplanned(ws):
    fixes(ws)
    (ws / "pkg" / "other.py").write_text("X = 2\n")


def adds_unplanned(ws):
    fixes(ws)
    (ws / "pkg" / "new.py").write_text("Y = 1\n")


def nothing(ws):
    pass


def _run(ws, plan_fn, execute, **kw):
    kw.setdefault("checks", ())
    return fix.run_issue(7, "title", "body", ws, plan_fn=plan_fn, execute=execute, pytest=PYTEST, **kw)


def test_a_fix_that_makes_the_planned_test_pass_inside_the_planned_files_is_resolved(ws):
    execute = _executor(fixes)
    rec = _run(ws, _planner(_plan()), execute)
    assert rec.resolved and rec.stage == "ok", rec.why
    assert rec.klass == "read_the_field" and len(rec.attempts) == 1
    assert rec.local_tokens == {"input": 40000, "output": 2000}
    assert "pkg/mod.py" in execute.prompts[0] and TEST in execute.prompts[0]


def test_a_local_diff_that_edits_the_test_is_refused_by_the_hash(ws):
    rec = _run(ws, _planner(_plan()), _executor(edits_the_test))
    assert not rec.resolved
    assert rec.stage == "hash" and "edited" in rec.why
    assert [a["stage"] for a in rec.attempts] == ["hash", "hash"]


def test_a_local_diff_that_deletes_the_test_is_refused_by_the_hash(ws):
    rec = _run(ws, _planner(_plan()), _executor(lambda w: (fixes(w), (w / TEST).unlink())))
    assert not rec.resolved and rec.stage == "hash" and "removed" in rec.why


@pytest.mark.parametrize("edit", [touches_unplanned, adds_unplanned])
def test_a_local_diff_that_touches_an_unplanned_file_is_refused(ws, edit):
    rec = _run(ws, _planner(_plan()), _executor(edit))
    assert not rec.resolved
    assert rec.stage == "scope" and "unplanned" in rec.why


def test_a_local_step_that_changes_nothing_is_refused(ws):
    rec = _run(ws, _planner(_plan()), _executor(nothing))
    assert not rec.resolved and rec.stage == "scope"


def test_a_planned_test_that_passes_at_base_is_refused_before_any_local_step(ws):
    execute = _executor(fixes)
    rec = _run(ws, _planner(_plan(FAILING.replace("== 2", "== 1"))), execute)
    assert not rec.resolved
    assert rec.stage == "base" and "passes at base" in rec.why
    assert execute.prompts == []


def test_a_planned_test_that_collects_nothing_is_refused_at_base(ws):
    execute = _executor(fixes)
    rec = _run(ws, _planner(_plan("X = 1\n")), execute)
    assert rec.stage == "base" and "did not run" in rec.why and execute.prompts == []


def test_a_test_that_imports_what_does_not_exist_yet_counts_as_failing_at_base(ws):
    code = "from pkg.mod import g\n\n\ndef test_g():\n    assert g() == 3\n"
    rec = _run(ws, _planner(_plan(code)), _executor(lambda w: (w / "pkg" / "mod.py").write_text(
        "def f():\n    return 1\n\n\ndef g():\n    return 3\n")))
    assert rec.resolved, rec.why


def test_a_still_failing_test_is_refused_and_the_second_attempt_is_told_why(ws):
    execute = _executor(lambda w: (w / "pkg" / "mod.py").write_text("def f():\n    return 3\n"), fixes)
    rec = _run(ws, _planner(_plan()), execute)
    assert rec.resolved and len(rec.attempts) == 2
    assert rec.attempts[0]["stage"] == "test"
    assert "refused: the planned test still fails" in execute.prompts[1]
    assert rec.local_tokens["input"] == 80000


def test_the_second_attempt_starts_again_from_base(ws):
    seen = []

    def second(w):
        seen.append(((w / "pkg" / "other.py").read_text(), (w / "pkg" / "new.py").exists()))
        fixes(w)
    rec = _run(ws, _planner(_plan()), _executor(lambda w: (touches_unplanned(w), adds_unplanned(w)), second))
    assert seen == [("X = 1\n", False)] and rec.resolved


def test_a_failing_check_is_refused(ws):
    rec = _run(ws, _planner(_plan()), _executor(fixes), checks=((sys.executable, "-c", "raise SystemExit(3)"),))
    assert not rec.resolved and "exit 3" in rec.why


@pytest.mark.parametrize("body, resolved", [("return 2", True), ("return '2'", False)])
def test_a_failing_selected_test_is_refused(ws, body, resolved):
    plan = _plan("from pkg.mod import f\n\n\ndef test_f():\n    assert str(f()) == '2'\n")
    rec = _run(ws, _planner(plan), _executor(lambda w: (w / "pkg" / "mod.py").write_text(f"def f():\n    {body}\n")),
               select=lambda w, files: ["tests/test_other.py"], attempts=1)
    assert rec.resolved is resolved and rec.stage == ("ok" if resolved else "tests")


@pytest.mark.parametrize("held, resolved", [("assert f() == 2", True), ("assert False", False)])
def test_the_merged_prs_own_test_must_also_pass(ws, held, resolved):
    _git(ws, "checkout", "-q", "-b", "pr")
    (ws / "tests" / "test_held.py").write_text(f"from pkg.mod import f\n\n\ndef test_h():\n    {held}\n")
    _git(ws, "add", "tests/test_held.py")
    _git(ws, "commit", "-qm", "pr")
    _git(ws, "checkout", "-q", "-")
    rec = _run(ws, _planner(_plan()), _executor(fixes), held_out=("tests/test_held.py",), held_out_ref="pr")
    assert rec.resolved is resolved and rec.stage == ("ok" if resolved else "held-out")


def test_out_of_class_and_over_cap_plans_escalate_without_a_local_step(ws):
    execute = _executor(fixes)
    rec = _run(ws, _planner({"class": "out_of_class", "why": "needs a migration"}), execute)
    assert rec.stage == "plan" and "out of class" in rec.why and not rec.resolved
    rec = _run(ws, _planner(_plan(), tokens={"input": 15000, "output": 4000, "cache_write": 2000,
                                             "cache_read": 10 ** 6}), execute)
    assert rec.stage == "plan" and "over the" in rec.why
    rec = _run(ws, _planner(_plan(), tokens={"input": 15000, "output": 4000, "cache_write": 0,
                                             "cache_read": 10 ** 6}), _executor(fixes))
    assert rec.resolved, "cache reads are not counted against the cap"
    assert execute.prompts == []


def test_plan_only_stops_after_the_base_check(ws):
    execute = _executor(fixes)
    rec = _run(ws, _planner(_plan()), execute, plan_only=True)
    assert rec.stage == "planned" and execute.prompts == [] and (ws / TEST).is_file()


@pytest.mark.parametrize("change, says", [
    ({"files": ["a.py", "b.py", "c.py", "d.py"]}, "1 to 3 files"),
    ({"files": []}, "1 to 3 files"),
    ({"files": ["harness/memory_store/migrations/v99.py"]}, "no plan may change"),
    ({"files": ["harness/memory_store/schema.py"]}, "no plan may change"),
    ({"files": ["harness/node_deploy.py"]}, "no plan may change"),
    ({"files": [TEST]}, "no plan may change"),
    ({"files": ["../outside.py"]}, "no plan may change"),
    ({"test_path": "harness/test_x.py"}, "not tests/test_"),
    ({"test_path": "tests/../x/test_x.py"}, "not tests/test_"),
    ({"test_code": "  "}, "no test code"),
    ({"class": "refactor"}, "is not one of"),
])
def test_a_plan_that_names_what_no_plan_may_is_refused(change, says):
    with pytest.raises(fix.PlanError, match=says.replace("(", r"\(")):
        fix.parse_plan(json.dumps({**_plan(), **change}))


def test_a_flaky_test_plan_may_change_an_existing_test_but_never_the_planned_one():
    got = fix.parse_plan(json.dumps({**_plan(klass="flaky_test"), "files": ["tests/conftest.py", "tests/test_other.py"]}))
    assert got.files == ("tests/conftest.py", "tests/test_other.py")


def test_a_plan_in_a_fenced_block_with_prose_around_it_parses():
    got = fix.parse_plan("Here it is:\n```json\n" + json.dumps(_plan()) + "\n```\nDone.")
    assert got.files == ("pkg/mod.py",) and got.test_path == TEST


def test_selected_tests_are_those_that_import_a_changed_module(ws):
    (ws / "tests" / "test_paren.py").write_text("from pkg import (\n    other,\n    mod,\n)\n")
    (ws / "tests" / "test_unrelated.py").write_text("import os\n")
    assert fix.selected_tests(ws, ["pkg/mod.py"]) == ["tests/test_other.py", "tests/test_paren.py"]
    assert fix.selected_tests(ws, ["README.md"]) == []


def test_a_candidate_is_a_merged_pr_with_a_test_and_at_most_three_source_files():
    c = fix.candidate(["harness/a.py", "tests/test_a.py", "tests/conftest.py"], "abc", 5, 6)
    assert c and c.base == "abc^" and c.held_out == ("tests/test_a.py",)
    assert fix.candidate(["harness/a.py"], "abc", 5, 6) is None
    assert fix.candidate(["a.py", "b.py", "c.py", "d.py", "tests/test_a.py"], "abc", 5, 6) is None
    assert fix.candidate(["harness/memory_store/migrations/v9.py", "tests/test_a.py"], "abc", 5, 6) is None


def test_records_land_in_delegations_and_the_cloud_plan_is_kept_out_of_local_tokens(tmp_path, ws):
    from harness import ledger
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "store.db")
    good = _run(ws, _planner(_plan()), _executor(fixes))
    fix.store(conn, good, "sohot-agent", at=1000.0)
    bad = fix.Record(8, fix.new_call_id(), klass="flaky_test", stage="hash", why="edited",
                     plan_tokens={"input": 100, "output": 50, "cache_write": 300, "cache_read": 999},
                     local_tokens={"input": 7, "output": 3})
    fix.store(conn, bad, "sohot-agent", replay=True, at=1001.0)
    rows = {r["issue"]: r for r in fix.stored(conn) + fix.stored(conn, replay=True)}
    assert rows[7] == {"issue": 7, "class": "read_the_field", "resolved": True, "why": rows[7]["why"],
                       "local": 42000, "cloud": 3500}
    assert rows[8]["resolved"] is False and rows[8]["cloud"] == 450 and rows[8]["why"].startswith("hash")
    lanes = {r[2] for r in ledger.delegation_rows(conn, 0)}
    assert lanes == {"fix:read_the_field", "fix-replay:flaky_test"}
    s = fix.summarize(list(rows.values()))
    assert s["in_class"]["resolved"] == 1 and s["in_class"]["fraction"] == 0.5
    assert s["classes"]["read_the_field"]["cloud_per_resolved"] == 3500
    assert any("in class" in line for line in fix.lines(s))
    conn.close()


def test_soh_fix_needs_an_issue_and_a_mode():
    from harness import cli
    a = cli.build_parser().parse_args(["fix", "12"])
    assert a.func(a) == 1
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["fix", "12", "--plan-only", "--execute"])
