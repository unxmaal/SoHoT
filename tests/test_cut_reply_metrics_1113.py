"""A repo reply cut before grading ranks and pairs as a graded failure, never below one. #1113."""
from __future__ import annotations

import json

from evals.core import Case, as_graded
from evals.runners.base import BaseRunner, RunnerError
from harness import paired, runs, winners

CASES = [f"repo-{i}" for i in range(9)]


def _rows(key, passes, cut):
    """passes resolved rows, then `cut` budget-cut rows with no metric, then graded failures."""
    out = []
    for i, case in enumerate(CASES):
        if i < passes:
            out.append({"case_id": case, "candidate": key, "passed": True, "seconds": 1.0, "detail": "",
                        "metrics": {"resolved": 1, "patch_applied": 1}})
        elif i < passes + cut:
            out.append({"case_id": case, "candidate": key, "passed": False, "seconds": 1.0,
                        "detail": "returned no answer", "failure_class": "token_budget_exhausted",
                        "limit": "max_tokens.repo>32768", "metrics": {}})
        else:
            out.append({"case_id": case, "candidate": key, "passed": False, "seconds": 1.0,
                        "detail": "fail_to_pass still failing", "failure_class": "content_failed",
                        "metrics": {"resolved": 0, "patch_applied": 1}})
    return out


def test_five_passes_with_four_cut_outrank_two_passes_with_none_cut(store_run, store_conn):
    store_run("cut", "repo", rows=_rows("org/five", 5, 4), cases_digest="exam", conn=store_conn)
    store_run("graded", "repo", rows=_rows("org/two", 2, 0), cases_digest="exam", conn=store_conn)
    got = winners.from_receipts(store_conn, plain_only=False, exam_of=lambda *k: (frozenset(CASES), "exam"))
    assert got["repo"]["candidate"] == "org/five"


def test_a_cut_reply_pairs_as_a_graded_failure_not_a_loss(store_run, store_conn):
    rid = store_run("pair", "repo", rows=_rows("org/inc", 0, 0) + _rows("org/ch", 0, 9), conn=store_conn)
    cell = paired.head_to_head(runs.rows(store_conn, rid), "org/inc", "org/ch", metric="resolved")
    assert (cell.lost, cell.gained) == (0, 0)


def test_a_stored_cut_row_is_backfilled_and_a_harness_failure_is_not(store_run, store_conn):
    rows = _rows("org/m", 0, 1)
    rows.append({"case_id": "env", "candidate": "org/m", "passed": False, "seconds": 1.0, "detail": "uv sync",
                 "failure_class": "environment_error", "metrics": {}})
    rid = store_run("old", "repo", rows=rows, conn=store_conn)
    store_run("code", "code", rows=[{**rows[0], "case_id": "lc1"}], conn=store_conn)
    store_conn.execute("UPDATE results SET metrics = '{}' WHERE failure_class = ?", ("token_budget_exhausted",))
    assert runs.grade_cut_rows(store_conn) == 1
    assert runs.grade_cut_rows(store_conn) == 0
    got = {r["case_id"]: r["metrics"] for r in runs.rows(store_conn, rid)}
    assert got["repo-0"] == {"resolved": 0, "patch_applied": 0} and got["env"] == {}
    code = store_conn.execute("SELECT metrics FROM results x JOIN runs r ON r.id = x.run_id WHERE r.lane = 'code'")
    assert json.loads(code.fetchone()[0]) == {}


class _Cut(BaseRunner):
    candidate, spec = "org/m", "org/m"

    def generate(self, case):
        raise RunnerError("returned no answer", failure_class="token_budget_exhausted")


def test_the_runner_records_a_cut_repo_reply_as_a_graded_failure():
    assert _Cut().run(Case("r", "repo", "fix it")).metrics == {"resolved": 0, "patch_applied": 0}
    assert _Cut().run(Case("c", "code", "write it")).metrics == {}


def test_a_graded_value_is_never_overwritten():
    assert as_graded("repo", "token_budget_exhausted", {"patch_applied": 1}) == {"resolved": 0, "patch_applied": 1}
    assert as_graded("repo", "crashed", {}) == {}
