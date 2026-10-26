"""Two runs that sat different exams are never ranked against each other; a lane ranks on its current exam. #1120."""
from __future__ import annotations

import argparse
import operator

import pytest

from evals import core
from evals import environment
from evals import run as er
from evals.core import Case, Result
from harness import baseline, runs, winners
from harness import memory_store as ms

IDS = frozenset(f"case-{i}" for i in range(10))


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def own(*keys):
    """A receipt specs map for keys that are their own spec, as evals.run writes it."""
    return {k: k for k in keys}


def current(digest="cur", ids=IDS, seen=None):
    """An exam_of whose current exam is `digest` over `ids` on every split and repeat."""
    def exam_of(lane, split, repeat):
        if seen is not None:
            seen.append((lane, split, repeat))
        return ids, digest
    return exam_of


@pytest.mark.parametrize("op", [operator.lt, operator.le, operator.gt, operator.ge, operator.eq, operator.ne])
def test_two_rows_on_different_digests_are_never_ordered(op):
    a = winners.order_key({"pass_rate": 1.0, "median_s": 1.0, "cases_digest": "396b0c99"}, ())
    b = winners.order_key({"pass_rate": 0.1, "median_s": 1.0, "cases_digest": "757951c2"}, ())
    with pytest.raises(winners.ExamMismatch, match="396b0c99.*757951c2"):
        op(a, b)
    with pytest.raises(winners.ExamMismatch):
        max([(b, False), (a, False)])


def test_on_one_digest_they_are_ordered_and_an_untagged_row_still_is():
    a = winners.order_key({"pass_rate": 1.0, "median_s": 1.0, "cases_digest": "x"}, ())
    b = winners.order_key({"pass_rate": 0.1, "median_s": 1.0, "cases_digest": "x"}, ())
    old = winners.order_key({"pass_rate": 0.5, "median_s": 1.0}, ())
    assert a > b and max([b, a]) is a and a != b
    assert b < old < a
    hash(a)


def test_from_receipts_ranks_only_runs_of_the_current_exam(conn, store_run):
    store_run("old", "repo", {"llamacpp:A": {"pass_rate": 1.0}}, specs=own("llamacpp:A"), cases_digest="old", generated="2026-10-01T00:00:00")
    store_run("new", "repo", {"llamacpp:B": {"pass_rate": 0.3}}, specs=own("llamacpp:B"), cases_digest="cur", generated="2026-10-02T00:00:00")
    got = winners.from_receipts(conn, exam_of=current())["repo"]
    assert (got["candidate"], got["cases_digest"]) == ("llamacpp:B", "cur")
    assert winners.from_receipts(conn, exam_of=current("none")) == {}


def test_a_run_that_missed_a_case_of_the_exam_is_not_ranked(conn, store_run):
    store_run("whole", "svg", {"q3-4b": {"pass_rate": 0.5}}, specs=own("q3-4b"), cases_digest="cur")
    part = [{"case_id": f"case-{i}", "candidate": "q3-30b", "passed": True, "seconds": 1.0, "peak_kb": 0,
             "detail": "", "output": None, "artifact_path": None, "warnings": [], "metrics": {}} for i in range(9)]
    store_run("part", "svg", rows=part, specs=own("q3-30b"), cases_digest="cur")
    assert winners.from_receipts(conn, exam_of=current())["svg"]["candidate"] == "q3-4b"


def test_each_run_is_checked_against_its_own_split_and_repeat(conn, store_run):
    seen = []
    store_run("h", "code", {"q3-4b": {"pass_rate": 0.5}}, specs=own("q3-4b"), cases_digest="cur", receipt={"split": "holdout", "repeat": 3})
    winners.from_receipts(conn, exam_of=current(seen=seen))
    assert seen == [("code", "holdout", 3)]


def test_a_lane_with_two_current_exams_ranks_on_the_newest_run_s(conn, store_run):
    store_run("dev", "code", {"q3-4b": {"pass_rate": 1.0}}, specs=own("q3-4b"), cases_digest="d", receipt={"split": "dev"},
              generated="2026-10-01T00:00:00")
    store_run("hold", "code", {"q3-30b": {"pass_rate": 0.2}}, specs=own("q3-30b"), cases_digest="h", receipt={"split": "holdout"},
              generated="2026-10-02T00:00:00")
    by_split = {"dev": "d", "holdout": "h"}
    got = winners.from_receipts(conn, exam_of=lambda lane, split, repeat: (IDS, by_split[split]))["code"]
    assert (got["candidate"], got["cases_digest"]) == ("q3-30b", "h")


def test_plain_only_keeps_composite_repo_specs_and_still_drops_an_alias_lanes_workflow(conn, store_run):
    # A failed repo reply is graded resolved 0 (#1302), so each row carries the metric as a stored one does.
    store_run("repo", "repo", {"llamacpp:Ornith": {"pass_rate": 0.2, "metrics": {"resolved": 0.2}},
                               "claude-code:opus": {"pass_rate": 0.1, "metrics": {"resolved": 0.1}}},
              specs=own("llamacpp:Ornith", "claude-code:opus"), cases_digest="cur")
    store_run("svg", "svg", {"local-large": {"pass_rate": 0.5}, "repair/local-large": {"pass_rate": 1.0}},
              specs={**own("local-large"), "repair/local-large": "repair:local-large"}, cases_digest="cur")
    got = winners.from_receipts(conn, exam_of=current())
    assert got["repo"]["candidate"] == "llamacpp:Ornith"
    assert got["svg"]["candidate"] == "local-large"


def test_a_default_beaten_only_on_an_old_exam_is_not_beaten_on_the_current_one(conn, store_run, monkeypatch):
    monkeypatch.setattr(winners, "typed", lambda: {"extract": "local-large"})
    store_run("old", "extract", {"local-large": {"pass_rate": 0.2}, "q3-4b": {"pass_rate": 0.9}},
              specs=own("local-large", "q3-4b"), cases_digest="old", generated="2026-10-01T00:00:00")
    store_run("cur", "extract", {"local-large": {"pass_rate": 0.9}, "q3-4b": {"pass_rate": 0.5}},
              specs=own("local-large", "q3-4b"), cases_digest="cur", generated="2026-10-02T00:00:00")
    assert winners.beaten_in(conn, exam_of=current())["extract"]["match"] == "exact"
    assert [r["state"] for r in winners.disagreements(conn, exam_of=current()) if r["modality"] == "extract"] == []
    assert winners.disagreements(conn, exam_of=current("old"))[0]["state"] == "beaten"


def test_a_room_the_default_did_not_sit_whole_is_not_a_comparison(conn, store_run, monkeypatch):
    monkeypatch.setattr(winners, "typed", lambda: {"extract": "local-large"})
    rows = [{"case_id": f"case-{i}", "candidate": key, "passed": key == "q3-4b", "seconds": 1.0, "peak_kb": 0,
             "detail": "", "output": None, "artifact_path": None, "warnings": [], "metrics": {}}
            for key, n in (("local-large", 4), ("q3-4b", 10)) for i in range(n)]
    store_run("cut", "extract", rows=rows, specs=own("local-large", "q3-4b"), cases_digest="cur")
    assert winners.beaten_in(conn, exam_of=current()) == {}


class _Runner:
    candidate = "fake/key"

    def warm(self):
        pass

    def run(self, case):
        return Result(case_id=case.id, candidate=self.candidate, passed=True, seconds=0.5, peak_kb=7, detail="")


@pytest.mark.parametrize("split, repeat", [("all", 2), ("holdout", 1)])
def test_the_exam_a_run_records_is_the_one_baseline_recomputes(monkeypatch, tmp_path, split, repeat):
    cases = [Case(id=f"c{i}", modality="svg", prompt=f"p{i}") for i in range(12)]
    monkeypatch.setattr(core, "load_cases", lambda path: cases)
    monkeypatch.setattr(er, "build_runner", lambda *a, **k: _Runner())
    monkeypatch.setattr(er, "warn_if_pressed", lambda: argparse.Namespace(as_dict=lambda: {}))
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {"hw_model": "Test,1", "os": "t", "arch": "a"})
    out = tmp_path / "out"
    args = argparse.Namespace(modality="svg", candidates="fake:spec", cases="x", out=str(out), screen=False,
                              repeat=repeat, split=split, adherence="", gateway="http://gw", from_winners=False)
    assert er._execute(args) == 0
    c = ms.connect()
    try:
        run = runs.find(c, lane="svg")[0]
        ids, digest = baseline.exam("svg", split, repeat, suite=cases)
        assert digest == run["cases_digest"]
        assert baseline.sat(run, runs.rows(c, run["id"]), "fake/key", memo={"suite": cases})
        assert not baseline.sat(run, runs.rows(c, run["id"]), "fake/key", memo={"suite": cases[:-1]})
    finally:
        c.close()
