"""#792: a schema-invalid claims reply counts in every expect-empty rate, and a stored row takes its stratum only from its own run."""
from __future__ import annotations

import json

import pytest

from evals import core
from harness import runs
from harness.checks import claims as C

SCHEMA = {"type": "object", "required": ["c"], "additionalProperties": False,
          "properties": {"c": {"type": "array", "items": {
              "type": "array", "prefixItems": [{"type": "string"}, {"type": "string"},
                                               {"type": "array", "items": {"type": "integer"}, "minItems": 1}],
              "minItems": 3, "maxItems": 3}}}}
EMPTY, ONE, CUT = json.dumps({"c": []}), json.dumps({"c": [["user-a", "a claim", [1]]]}), '{"c": [["user-a", "a cl'


@pytest.mark.parametrize("reply", [EMPTY, ONE, CUT])
def test_every_check_path_on_an_expect_empty_case_reports_the_expect_empty_counts(reply):
    got = C.check(reply, SCHEMA, [], expect_empty=True).metrics
    assert got["claims_empty_cases"] == 1 and got["claims_empty_kept"] == int(reply == EMPTY)


def _row(case, reply, empty):
    out = C.check(reply, SCHEMA, [], expect_empty=empty)
    return core.Result(case, "m", out.ok, 1.0, 0, out.reason, metrics=out.metrics)


def test_a_cut_reply_to_an_expect_empty_case_counts_against_the_empty_rate():
    rows = [_row("a", EMPTY, True), _row("b", CUT, True)]
    for r in rows:
        r.metrics[C.STRATUM] = 1
    got = core.summarize(rows)["m"]["metrics"]
    assert got["claims_empty_rate"] == got["claims_case_specificity"] == 0.5


def _stored(case, candidate, metrics, passed=False):
    return {"case_id": case, "candidate": candidate, "passed": passed, "seconds": 1.0, "detail": "",
            "metrics": metrics, "failure_class": "" if passed else "token_budget_exhausted"}


INVALID = {"claims_schema_valid": 0, "claims_judge_calibrated": 0, "claims_matcher_version": 2}
VALID_EMPTY = {"claims_schema_valid": 1, "claims_emitted": 0, "claims_empty_kept": 1, "claims_empty_cases": 1,
               "claims_empty_rate": 1.0}
VALID_CLAIMS = {"claims_schema_valid": 1, "claims_emitted": 1}


def test_a_legacy_row_takes_its_stratum_from_its_own_run_and_nowhere_else(store_run, store_conn):
    old = store_run("old", "claims", conn=store_conn, rows=[
        _stored("e", "x", INVALID), _stored("e", "y", VALID_EMPTY, passed=True),
        _stored("k", "x", INVALID), _stored("k", "y", VALID_CLAIMS, passed=True),
        _stored("u", "x", INVALID), _stored("u", "y", INVALID)])
    store_run("other", "claims", conn=store_conn, rows=[_stored("u", "z", VALID_EMPTY, passed=True)])
    stamped = store_run("stamped", "claims", conn=store_conn, rows=[_stored("s", "x", {**INVALID, C.STRATUM: 1})])
    store_run("code", "code", conn=store_conn, rows=[_stored("e", "x", INVALID), _stored("e", "y", VALID_EMPTY)])
    assert runs.stamp_claims_strata(store_conn) == 3
    assert runs.stamp_claims_strata(store_conn) == 0
    got = {(r["case_id"], r["candidate"]): r["metrics"] for r in runs.rows(store_conn, old)}
    assert got[("e", "x")] == {**INVALID, C.STRATUM: 1, "claims_empty_cases": 1, "claims_empty_kept": 0,
                               "claims_empty_rate": 0.0}
    assert got[("k", "x")] == {**INVALID, C.STRATUM: 0}
    assert got[("u", "x")] == got[("u", "y")] == INVALID
    assert got[("e", "y")] == VALID_EMPTY
    assert runs.rows(store_conn, stamped)[0]["metrics"]["claims_empty_cases"] == 1
    code = store_conn.execute("SELECT x.metrics FROM results x JOIN runs r ON r.id = x.run_id "
                              "WHERE r.lane = 'code' AND x.candidate = 'x'")
    assert json.loads(code.fetchone()[0]) == INVALID


def test_a_backfilled_run_covers_every_row_it_can_know(store_run, store_conn):
    rid = store_run("old", "claims", conn=store_conn, rows=[
        _stored("e", "x", INVALID), _stored("e", "y", VALID_EMPTY, passed=True),
        _stored("k", "x", VALID_CLAIMS, passed=True), _stored("k", "y", VALID_CLAIMS, passed=True)])
    before = {c: row["metric_n"]["claims_balanced"] for _, s, _ in runs.summaries(store_conn, lane="claims")
              for c, row in s.items() if "claims_balanced" in row.get("metric_n", {})}
    assert before == {"y": 2}
    runs.stamp_claims_strata(store_conn)
    after = {c: (row["metric_n"]["claims_balanced"], row["metrics"]["claims_balanced"])
             for run, s, _ in runs.summaries(store_conn, lane="claims") if run["id"] == rid for c, row in s.items()}
    assert after == {"x": (2, 0.5), "y": (2, 1.0)}
