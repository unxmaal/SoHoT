"""#1302: a crashed repo reply ranks as a graded failure, and the paired gate never adopts a challenger that lost more cells."""
from __future__ import annotations

import json

from evals.core import Case, as_graded
from evals.runners.base import BaseRunner, RunnerError
from harness import adopt, holdout, runs, winners
from harness.memory_store import migrations

CASES = [f"repo-{i}" for i in range(40)]
SPLIT = holdout.Split("repo", dev=tuple(CASES[:12]), holdout=tuple(CASES[12:]), too_small=False)


def _rows(key, passes, crashed=0):
    """`passes` resolved rows, then `crashed` crashed rows with no metric, then graded failures."""
    out = []
    for i, case in enumerate(CASES):
        row = {"case_id": case, "candidate": key, "passed": i < passes, "seconds": 1.0, "detail": "",
               "metrics": {"resolved": int(i < passes), "patch_applied": 1}}
        if passes <= i < passes + crashed:
            row.update(detail="claude -p: API Error", failure_class="crashed", metrics={})
        elif i >= passes:
            row.update(failure_class="content_failed")
        out.append(row)
    return out


def test_a_crashed_repo_row_scores_as_a_graded_failure():
    assert as_graded("repo", "crashed", {}) == {"resolved": 0, "patch_applied": 0}
    assert as_graded("repo", "timeout", {"patch_applied": 1}) == {"resolved": 0, "patch_applied": 1}
    assert as_graded("repo", "environment_error", {}) == {}
    assert as_graded("repo", "", {}) == {}
    assert as_graded("code", "crashed", {}) == {}


class _Crash(BaseRunner):
    candidate, spec = "org/m", "org/m"

    def generate(self, case):
        raise RunnerError("claude -p: API Error", failure_class="crashed")


def test_the_runner_records_a_crashed_repo_reply_as_a_graded_failure():
    assert _Crash().run(Case("r", "repo", "fix it")).metrics == {"resolved": 0, "patch_applied": 0}


def test_four_crashed_rows_do_not_outrank_a_sixty_point_gap():
    rows = [{**r, "metrics": as_graded("repo", r.get("failure_class", ""), r["metrics"])}
            for r in _rows("org/strong", 28, crashed=4)] + _rows("org/weak", 4)
    strong, weak = adopt._summary(rows, "org/strong"), adopt._summary(rows, "org/weak")
    assert winners.primary(strong, "repo") > winners.primary(weak, "repo")
    assert adopt.better(weak, strong, "repo") and not adopt.better(strong, weak, "repo")


def test_the_paired_gate_never_adopts_a_challenger_that_lost_more_cells_than_it_gained(monkeypatch):
    rows = _rows("org/strong", 28) + _rows("org/weak", 4)
    # Whatever the metric gate says, the paired cells decide the direction.
    monkeypatch.setattr(adopt, "better", lambda incumbent, challenger, lane="": True)
    v = adopt.decide("repo", adopt._summary(rows, "org/strong"), adopt._summary(rows, "org/weak"), rows, split=SPLIT)
    assert not v.adopt and "significantly worse" in v.why, v.why
    assert adopt.outcome_of(v) == ("declined", "candidate")
    held = adopt.Verdict("repo", "org/strong", "org/weak", True, "won", adopt.MEASURED)
    got = adopt.confirm(held, rows, SPLIT)
    assert not got.adopt and "significantly worse" in got.why, got.why


def test_schema_84_grades_stored_crashed_repo_rows(store_run, store_conn):
    rid = store_run("old", "repo", rows=_rows("org/m", 1, crashed=2)[:3], conn=store_conn)
    store_conn.execute("UPDATE results SET metrics = '{}' WHERE failure_class = 'crashed'")
    v84 = next(m for m in migrations.steps() if m.VERSION == 84)
    v84.data(store_conn)
    got = {r["case_id"]: r["metrics"] for r in runs.rows(store_conn, rid)}
    assert got["repo-1"] == got["repo-2"] == {"resolved": 0, "patch_applied": 0}
    assert json.loads(store_conn.execute("SELECT metrics FROM results WHERE case_id = 'repo-0'").fetchone()[0])["resolved"] == 1
