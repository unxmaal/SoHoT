"""The repo lane's repair harness: a bounded tool loop over the repo executor, graded by the patch grader. #890."""
import dataclasses
import json
from pathlib import Path

import pytest

from evals import repo, repo_size, repo_tools, run
from evals.core import Receipt, comparable
from evals.runners import repo_repair
from evals.runners.repo_repair import RepoRepairRunner
from harness import completion, identity, reasons
from tests.test_repo_lane import (BASE_FILES, BUGGY, DARWIN, FIXED, HIDDEN, _diff, _here,  # noqa: F401
                                  _two_commits, upstream)


def _call(name, **args):
    return {"tool_calls": [{"id": f"c-{name}", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}]}


def _scripted(turns, seen=None, tokens=10):
    """chat() that answers each turn from `turns` in order, recording the messages it was sent."""
    it = iter(turns)

    def chat(messages, **kw):
        if seen is not None:
            seen.append([dict(m) for m in messages])
        msg = next(it, {"content": "done"})
        return completion.Completion(msg.get("content") or "", {"completion_tokens": tokens, "prompt_tokens": 5},
                                     [], {}, model="fake", message={"role": "assistant", **msg}, finish="stop")
    return chat


def _runner(turns, seen=None, denied=None, tokens=10):
    r = RepoRepairRunner("http://unused", "fake", chat=_scripted(turns, seen, tokens), max_tokens=4000)
    r.attempt = lambda params: repo.Attempt.open(params, env=_here)
    r.denied = denied
    return r


def _record(row):
    return json.loads(row.output)


@DARWIN
def test_the_tool_loop_applies_a_patch_and_the_grader_sees_it(upstream):
    row = _runner([_call("read_file", path="pkg/mod.py"), _call("apply_patch", patch=_diff(BUGGY, FIXED)),
                   _call("run_tests"), _call("finish", summary="add adds")]).run(upstream)
    got = _record(row)
    assert row.passed and got["grade"]["resolved"] and got["stopped"] == "finished"
    assert "+    return a + b" in got["diff"] and got["harness"] == "repair"
    assert [c["name"] for s in got["steps"] for c in s["calls"]] == ["read_file", "apply_patch", "run_tests", "finish"]
    assert all(c["out_bytes"] > 0 for s in got["steps"] for c in s["calls"])
    assert "return a + b" in got["steps"][1]["calls"][0]["args"]
    assert row.metrics["repair_generated_tokens"] == 40 and row.metrics["repair_test_runs"] == 1


@DARWIN
def test_a_finish_with_no_patch_is_graded_unresolved(upstream):
    row = _runner([_call("finish")]).run(upstream)
    assert not row.passed and row.failure_class == reasons.INVALID_PATCH and _record(row)["diff"] == ""


def test_a_patch_without_git_s_a_and_b_prefixes_applies(upstream):
    bare = _diff(BUGGY, FIXED).split("\n", 1)[1].replace("--- a/", "--- ").replace("+++ b/", "+++ ")
    seen = []
    _runner([_call("apply_patch", patch=bare), _call("finish")], seen).run(upstream)
    assert [m["content"] for m in seen[-1] if m["role"] == "tool"][0] == "applied to pkg/mod.py"
    assert repo_tools._prefixed("--- /dev/null\n+++ b/x\n") == "--- /dev/null\n+++ b/x\n"


def test_a_patch_that_changes_nothing_says_so(upstream):
    same = _diff(BUGGY, BUGGY.replace("return a - b", "return a - b ", 1)).replace("return a - b \n", "return a - b\n")
    seen = []
    _runner([_call("apply_patch", patch=same), _call("finish")], seen).run(upstream)
    assert "unchanged from base" in [m["content"] for m in seen[-1] if m["role"] == "tool"][0]


def test_a_bad_patch_returns_the_apply_error_to_the_model(upstream):
    seen = []
    bad = _diff("def nope():\n    pass\n", "def nope():\n    return 1\n")
    _runner([_call("apply_patch", patch=bad), _call("finish")], seen).run(upstream)
    tool = [m for m in seen[1] if m["role"] == "tool"]
    assert tool and tool[-1]["content"].startswith("error: git apply:") and "patch does not apply" in tool[-1]["content"]


def test_a_patch_to_a_test_file_or_the_git_link_is_refused(upstream):
    seen = []
    edit = _diff("x\n", "y\n", path="tests/test_mod.py")
    _runner([_call("apply_patch", patch=edit), _call("read_file", path=".git"), _call("finish")], seen).run(upstream)
    tool = [m["content"] for m in seen[-1] if m["role"] == "tool"]
    assert "test file" in tool[0] and "not part of the repository" in tool[1]


def test_run_tests_will_not_name_a_test_file_the_base_lacks(upstream):
    case = _two_commits(Path(upstream.params["source_repo"] + "-new"), BASE_FILES,
                        {"pkg/mod.py": FIXED, "tests/test_new.py": HIDDEN},
                        fail_to_pass=["tests/test_new.py::test_add_hidden_marker"], pass_to_pass=[])
    seen = []
    _runner([_call("run_tests", path="tests/test_new.py"), _call("run_tests"), _call("finish")], seen).run(case)
    tool = [m["content"] for m in seen[-1] if m["role"] == "tool"]
    assert "not a test file of this repository" in tool[0] and "has no test file for this task" in tool[1]


LEAK = '''import subprocess
FOUND = subprocess.run(["git", "--git-dir", {mirror!r}, "show", {fix!r} + ":tests/test_mod.py"],
                       capture_output=True, text=True).stdout
try:
    FOUND += open({src!r} + "/tests/test_mod.py").read()
except OSError as exc:
    FOUND += repr(exc)
raise RuntimeError("LEAKED<" + FOUND + ">")
'''


def _leak_output(upstream, denied):
    """What run_tests prints after a patch that makes the package read the fix's tests at import."""
    p = upstream.params
    mirror = str(repo.mirror_path(p["source_repo"]))
    leak = BUGGY + LEAK.format(mirror=mirror, fix=p["fix"], src=p["source_repo"])
    seen = []
    r = _runner([_call("apply_patch", patch=_diff(BUGGY, leak)), _call("run_tests"), _call("finish")], seen,
                denied=denied)
    r.run(upstream)
    return [m["content"] for m in seen[-1] if m["role"] == "tool"][1]


@DARWIN
def test_run_tests_cannot_read_the_hidden_tests_from_the_mirror_or_the_source(upstream):
    out = _leak_output(upstream, None)
    assert "LEAKED<" in out and "test_add_hidden_marker" not in out


@DARWIN
def test_the_leak_control_does_read_the_hidden_tests_when_nothing_is_hidden(upstream):
    assert "test_add_hidden_marker" in _leak_output(upstream, [])


@pytest.mark.parametrize("cap,value,cls,limit", [
    ("MAX_STEPS", 2, reasons.STEP_CAP, "repair_max_steps>2"),
    ("MAX_TOKENS", 15, reasons.TOKEN_BUDGET_EXHAUSTED, "repair_max_tokens>15"),
    ("CASE_TIMEOUT_S", 0.0, reasons.TIMEOUT, "repair_case_timeout_s>0"),
])
def test_each_cap_stops_the_loop_and_names_itself(upstream, monkeypatch, cap, value, cls, limit):
    monkeypatch.setattr(repo_repair, cap, value)
    row = _runner([_call("list_files")] * 5).run(upstream)
    got = _record(row)
    assert not row.passed and row.failure_class == cls and row.limit == limit
    assert got["stopped"] == {"MAX_STEPS": "step cap", "MAX_TOKENS": "token cap", "CASE_TIMEOUT_S": "time cap"}[cap]
    assert got["caps"]["repair_max_steps"] == repo_repair.MAX_STEPS
    assert len(got["steps"]) == {"MAX_STEPS": 2, "MAX_TOKENS": 2, "CASE_TIMEOUT_S": 0}[cap]


def test_each_turn_s_reply_budget_fits_what_the_served_context_leaves(upstream):
    asked = []
    r = _runner([_call("list_files"), _call("finish")])
    chat = r.chat
    r.chat = lambda messages, **kw: asked.append(kw["max_tokens"]) or chat(messages, **kw)
    r.served_ctx = 3000
    row = r.run(upstream)
    assert len(asked) == 2 and 0 < asked[1] < asked[0] < 3000 and r.max_tokens == 4000
    r2 = _runner([_call("list_files")])
    r2.served_ctx = 50
    row = r2.run(upstream)
    assert row.failure_class == reasons.CONTEXT_EXCEEDED and row.limit == "served_ctx>50"


def test_fewer_than_four_cases_print_as_one_group_not_a_quartile():
    table = repo_size.quartiles([{"case_id": "a", "candidate": "x", "passed": True}], {"a": 2})
    assert table[0]["quartile"] == 0 and "all    2-2" in repo_size.text(table)


def test_calls_past_the_per_turn_cap_are_not_run_and_the_model_is_told(upstream, monkeypatch):
    monkeypatch.setattr(repo_repair, "CALLS_PER_TURN", 2)
    many = {"tool_calls": [_call("list_files")["tool_calls"][0] | {"id": f"c{i}"} for i in range(5)]}
    seen = []
    row = _runner([many, _call("finish")], seen).run(upstream)
    got = _record(row)
    first = got["steps"][0]
    assert len(first["calls"]) == 2 and first["calls_cut"] == 3 and row.metrics["repair_calls_cut"] == 3
    sent = seen[1]
    assert len(sent[2]["tool_calls"]) == 2 and [m["role"] for m in sent[3:]] == ["tool", "tool"]
    assert "3 more tool calls" in sent[-1]["content"] and "at most 2" in sent[-1]["content"]
    assert got["caps"]["repair_calls_per_turn"] == 2


def test_a_long_tool_result_is_cut_to_the_output_cap(upstream, monkeypatch):
    monkeypatch.setattr(repo_tools, "OUTPUT_CAP", 40)
    seen = []
    _runner([_call("read_file", path="pkg/mod.py"), _call("finish")], seen).run(upstream)
    tool = [m["content"] for m in seen[-1] if m["role"] == "tool"][0]
    assert "[cut:" in tool and len(tool.encode()) < 120


def _sized(tmp_path, name, lines):
    body = "".join(f"x{i} = {i}\n" for i in range(lines))
    return _two_commits(tmp_path / name, BASE_FILES, {"pkg/big.py": body, "tests/test_big.py": "x = 1\n" * 50})


def test_the_size_selector_counts_non_test_lines_and_keeps_the_small_fixes(tmp_path):
    small, big = _sized(tmp_path, "small", 5), _sized(tmp_path, "big", 30)
    big = dataclasses.replace(big, id="big")
    assert repo_size.sizes([small, big]) == {"fixture": 5, "big": 30}
    assert [c.id for c in repo_size.at_most([small, big], 20)] == ["fixture"]
    assert [c.id for c in repo_size.at_most([small, big], 0)] == ["fixture", "big"]
    args = run.parse_args(["--modality", "repo", "--candidates", "x", "--max-fix-lines", "20"])
    assert [c.id for c in run.fix_sized([small, big], args)] == ["fixture"]


def test_the_quartile_table_splits_cases_by_size_and_counts_passes_per_candidate():
    by = {f"c{i}": i for i in range(1, 9)}
    rows = [{"case_id": k, "candidate": c, "passed": c == "a" or v < 3} for k, v in by.items() for c in ("a", "b")]
    table = repo_size.quartiles(rows, by)
    assert [q["lines"] for q in table] == [(1, 2), (3, 4), (5, 6), (7, 8)]
    assert table[0]["passed"] == {"a": (2, 2), "b": (2, 2)} and table[1]["passed"] == {"a": (2, 2), "b": (0, 2)}
    assert "Q1    1-2" in repo_size.text(table)


def test_the_repair_harness_keys_its_rows_apart_and_its_receipt_is_not_comparable():
    assert RepoRepairRunner("http://unused", "Ornith").candidate == "repair/Ornith"
    base = dict(modality="repo", case_ids=("a",), repeat=1, sampling={}, gateway="g")
    patch, fix = Receipt(**base), Receipt(**base, harness="repair")
    ok, why = comparable(patch, fix)
    assert not ok and "different harness" in why
    assert Receipt.from_dict(fix.as_dict()).harness == "repair" and "harness" not in patch.as_dict()


def test_winners_never_rank_a_repair_run_on_the_exam():
    from harness import baseline
    exam = lambda lane, split, repeat: ({"a"}, "d1")  # noqa: E731
    rows = [{"candidate": "x", "case_id": "a"}]
    sat = {"lane": "repo", "cases_digest": "d1", "receipt": {}}
    assert baseline.sat(sat, rows, "x", exam_of=exam)
    assert not baseline.sat({**sat, "receipt": {"harness": "repair"}}, rows, "x", exam_of=exam)


def test_a_repair_identity_never_matches_a_patch_identity_and_patch_keeps_its_knobs():
    patch = identity.settings("repo", "x", 100)
    assert not set(patch["knobs"]) & set(repo_repair_knobs())
    repair = identity.settings("repo", "x", 100, repo_harness="repair")
    assert set(repo_repair_knobs()) <= set(repair["knobs"])


def repo_repair_knobs():
    from harness.knobs.repo import REPAIR
    return REPAIR


def test_the_cli_takes_a_harness_only_for_the_repo_lane():
    args = run.parse_args(["--modality", "code", "--candidates", "x", "--harness", "repair"])
    with pytest.raises(SystemExit, match="repo lane"):
        run.harness_of(args)
    assert run.harness_of(run.parse_args(["--modality", "repo", "--candidates", "x", "--harness", "repair"])) == "repair"
    with pytest.raises(SystemExit, match="cloud-opus"):
        run._repo_repair_runner("claude-code:claude-opus-5-5", "", 0)
