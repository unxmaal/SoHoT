"""A row the harness failed before a model ran is neither a failure nor a gap in metric coverage. #1116."""
from __future__ import annotations

from harness import adopt, baseline, runs, winners
from harness import memory_store as ms


def _rows(key, passes, graded, env=0, prefix="repo"):
    """passes resolved rows, then graded failures, then `env` environment_error rows with no metric."""
    out = []
    for i in range(passes + graded + env):
        row = {"case_id": f"{prefix}-{i}", "candidate": key, "passed": i < passes, "seconds": 1.0,
               "peak_kb": 0, "detail": "", "warnings": [], "metrics": {"resolved": int(i < passes)}}
        if i >= passes + graded:
            row.update(detail="uv sync failed", failure_class="environment_error", metrics={})
        elif i >= passes:
            row.update(detail="fail_to_pass still failing", failure_class="content_failed")
        out.append(row)
    return out


def test_environment_errors_leave_the_primary_key_and_rate_unchanged():
    clean = runs.summarize(_rows("org/a", 12, 25))["org/a"]
    hit = runs.summarize(_rows("org/b", 12, 25, env=4))["org/b"]
    assert (clean["total"], hit["total"], hit["judged"]) == (37, 41, 37)
    assert winners.primary(hit, "repo") == winners.primary(clean, "repo") == (True, 1.0, 0.3243)
    assert winners.order_key(hit, ("resolved",), "repo")[:2] == winners.order_key(clean, ("resolved",), "repo")[:2]


def test_environment_errors_are_not_failures_on_a_pass_rate_lane():
    clean = runs.summarize(_rows("org/a", 3, 3))["org/a"]
    hit = runs.summarize(_rows("org/b", 3, 3, env=6))["org/b"]
    assert winners.primary(hit, "code") == winners.primary(clean, "code") == (True, 1.0, 0.5)


def test_a_candidate_the_harness_never_ran_has_no_metric_and_sorts_below():
    never = runs.summarize(_rows("org/n", 0, 0, env=5))["org/n"]
    some = runs.summarize(_rows("org/s", 1, 4))["org/s"]
    assert never["judged"] == 0 and winners.primary(never, "repo") == (False, 1.0, 0.0)
    assert winners.shared_metrics([never, some], "repo") == ("resolved",)
    assert not adopt.better(some, never, "repo")


def test_twelve_of_forty_one_with_four_environment_errors_outranks_five_of_thirty_nine(store_run, store_conn):
    store_run("opus", "repo", rows=_rows("org/opus", 12, 25, env=4), conn=store_conn)
    store_run("ornith", "repo", rows=_rows("org/ornith", 5, 34), conn=store_conn)
    assert winners.from_receipts(store_conn, plain_only=False)["repo"]["candidate"] == "org/opus"


def test_adoption_and_measured_baselines_see_the_environment_errors(store_run):
    rows = _rows("org/b", 2, 4, env=4) + _rows("org/a", 2, 8)
    assert adopt._summary(rows, "org/b")["judged"] == 6
    assert adopt.better(adopt._summary(rows, "org/a"), adopt._summary(rows, "org/b"), "repo")
    conn = ms.connect()
    ms.remember_machine(conn)
    store_run("b", "repo", rows=rows[:10], specs={"org/b": "org/b"}, cases_digest="exam", conn=conn)
    store_run("a", "repo", rows=rows[10:], specs={"org/a": "org/a"}, cases_digest="exam", conn=conn)
    ids = {r["case_id"] for r in rows}
    got = baseline.measured(conn, "repo", ids, "exam", [ms.machine_row(conn)])
    assert [m["spec"] for m in got] == ["org/b", "org/a"]
