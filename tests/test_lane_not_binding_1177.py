"""A model with no ladder of its own is not swept on a lane whose stored cuts do not convert, nor one a paired run shows below its incumbent (#1177)."""
import json

import pytest

from harness import binding, reverify, runs, sweeps
from tests.test_knob_sweeps import ENV, queued
from tests.test_reply_budget_binding_1020 import DAY_AT, LOW_SAMPLING, VENDOR, VENDOR_SPEC, _row, conn, record  # noqa: F401

QWOPUS = "llamacpp:qwopus"


@pytest.fixture
def serve(monkeypatch):
    def to(spec, incumbent=""):
        monkeypatch.setattr(reverify, "served", lambda c: {"repo": {
            "lane": "repo", "spec": spec, "candidate_id": None, "incumbent": incumbent, "incumbent_id": None}})
    return to


def lane_cuts(conn, n, spec="ornith"):
    """`n` replies of `spec` cut at 32768 that finish wrong at 65536 with the same settings; 10 cases pass in both."""
    cases = [f"o{i}" for i in range(n + 10)]
    record(conn, spec, {c: "cut" for c in cases[:n]} | {c: "pass" for c in cases[n:]},
           top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 9000)
    record(conn, spec, {c: "wrong" for c in cases[:n]} | {c: "pass" for c in cases[n:]},
           top=65536, sampling=LOW_SAMPLING, at=DAY_AT - 8000)


def new_model(conn):
    """The new spec: one run at the lane's budget, some replies cut, none given more room."""
    cases = [f"q{i}" for i in range(12)]
    record(conn, QWOPUS, {c: "cut" for c in cases[:4]} | {c: "pass" for c in cases[4:7]}
           | {c: "wrong" for c in cases[7:]}, top=32768, sampling=VENDOR, at=DAY_AT - 3600)


def test_tonight_a_new_model_on_a_lane_whose_22_cuts_do_not_convert_is_not_swept(conn, serve):
    """Replays 2026-10-23: 21 confounded Ornith cuts plus 1 more, a new spec with no ladder; nothing is queued."""
    serve(QWOPUS)
    lane_cuts(conn, 1, "qwen4b")
    cases = [f"c{i}" for i in range(39)]
    record(conn, "ornith", {c: "cut" for c in cases[:21]} | {c: "wrong" for c in cases[21:]},
           top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 7200)
    record(conn, VENDOR_SPEC, {c: ("wrong", (32768,)) for c in cases[:17]} | {c: ("cut", (32768,)) for c in cases[17:21]}
           | {c: "wrong" for c in cases[21:]}, top=65536, sampling=VENDOR, ladder=(32768, 65536), at=DAY_AT - 7000)
    new_model(conn)
    got = sweeps.check(conn, now=DAY_AT)
    assert got["queued"] == [] and queued(conn) == []
    entry = got["planned"][0]
    assert entry["spec"] == QWOPUS
    assert entry["skip"].startswith("not binding on the lane: 0 of 22 cut replies pass with more room (")
    assert f"no stored run of {QWOPUS} gave its cuts more room" in entry["skip"]
    row = dict(conn.execute("SELECT * FROM knob_sweeps").fetchone())
    assert row["outcome"] == sweeps.NOT_BINDING_LANE and row["jobs"] == "[]" and row["settled_at"] == DAY_AT
    cost, trigger = json.loads(row["cost"]), json.loads(row["trigger"])
    assert cost["cut"] == 22 and cost["passed"] == 0 and len(cost["where"]) == 2
    assert trigger["cut"] == 22 and trigger["convertible"] == 0 and trigger["runs"] == cost["where"]
    sweeps.check(conn, now=DAY_AT + 60)
    assert conn.execute("SELECT COUNT(*) FROM knob_sweeps").fetchone()[0] == 1


def test_a_lane_with_no_evidence_still_sweeps_the_new_model(conn, serve):
    serve(QWOPUS)
    new_model(conn)
    got = sweeps.check(conn, now=DAY_AT)
    assert got["planned"][0]["evidence"]["binding"] is None
    assert len(queued(conn)) == 6


def test_fewer_cuts_than_the_knob_still_sweep_and_as_many_do_not(conn, serve, monkeypatch):
    serve(QWOPUS)
    lane_cuts(conn, sweeps.LANE_MIN_CUTS - 1)
    new_model(conn)
    assert sweeps.plan(conn, now=DAY_AT)[0]["skip"] == ""
    monkeypatch.setattr(sweeps, "LANE_MIN_CUTS", sweeps.LANE_MIN_CUTS - 1)
    assert sweeps.plan(conn, now=DAY_AT)[0]["skip"].startswith("not binding on the lane")


def test_one_lane_conversion_still_sweeps(conn, serve):
    serve(QWOPUS)
    lane_cuts(conn, 30)
    record(conn, "glm", {"g0": "cut", "g1": "pass"}, top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 6000)
    record(conn, "glm", {"g0": "pass", "g1": "pass"}, top=65536, sampling=LOW_SAMPLING, at=DAY_AT - 5000)
    new_model(conn)
    entry = sweeps.plan(conn, now=DAY_AT)[0]
    assert entry["skip"] == "" and entry["evidence"]["binding"] is None


def test_the_models_own_ladder_outranks_the_lane(conn, serve):
    serve("ornith")
    lane_cuts(conn, 30, "glm")
    cases = [f"c{i}" for i in range(10)]
    record(conn, "ornith", {c: "cut" for c in cases}, top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 4000)
    record(conn, "ornith", {c: "pass" for c in cases}, top=65536, sampling=LOW_SAMPLING, at=DAY_AT - 3000)
    entry = sweeps.plan(conn, now=DAY_AT)[0]
    assert entry["evidence"]["binding"] is True and entry["skip"] == ""


def test_a_new_converting_lane_run_reopens_a_lane_not_binding_row(conn, serve):
    serve(QWOPUS)
    lane_cuts(conn, 25)
    new_model(conn)
    sweeps.check(conn, now=DAY_AT)
    assert queued(conn) == []
    record(conn, "glm", {"g0": "cut", "g1": "pass"}, top=32768, sampling=LOW_SAMPLING, at=DAY_AT + 10)
    record(conn, "glm", {"g0": "pass", "g1": "pass"}, top=65536, sampling=LOW_SAMPLING, at=DAY_AT + 20)
    sweeps.check(conn, now=DAY_AT + 60)
    assert len(queued(conn)) == 6


def record_pair(conn, outcomes: dict, at):
    """One paired run: spec -> case -> 'pass'|'wrong'."""
    rows = [_row(spec, case, got, 32768) for spec, cases in outcomes.items() for case, got in cases.items()]
    receipt = {"modality": "repo", "max_tokens": 32768, "budget_ladder": [], "sampling": LOW_SAMPLING}
    return runs.record(conn, f"runs/pair{int(at)}-repo",
                       {"receipt": receipt, "environment": ENV, "specs": {s: s for s in outcomes}, "rows": rows}, at=at)


def _cases(passed, n, prefix="p"):
    return {f"{prefix}{i}": ("pass" if i < passed else "wrong") for i in range(n)}


def test_a_served_model_a_paired_run_shows_below_its_incumbent_is_not_swept(conn, serve):
    serve("ornith", incumbent="qwen4b")
    rid = record_pair(conn, {"ornith": _cases(1, 6), "qwen4b": _cases(3, 6)}, DAY_AT - 5000)
    swept, why = sweeps.model(conn, reverify.served(conn)["repo"], runs.here(conn))
    assert swept["spec"] == "qwen4b"
    assert why.startswith(f"ornith passed 1 of 6 beside qwen4b's 3 in run {rid}; sweeping qwen4b")


def test_a_fallback_a_paired_run_shows_below_the_served_model_is_passed_over(conn, serve):
    serve("weak")
    record_pair(conn, {"qwopus": _cases(3, 6), "weak": _cases(4, 6)}, DAY_AT - 6000)
    record(conn, "weak", _cases(0, 6, "w"), top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 5000)
    record(conn, "glm", _cases(2, 10, "g"), top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 4000)
    swept, why = sweeps.model(conn, reverify.served(conn)["repo"], runs.here(conn))
    assert swept["spec"] == "glm" and "the best passing (2 of 10" in why


def test_a_paired_run_above_the_incumbent_keeps_the_served_model(conn, serve):
    serve("ornith", incumbent="qwen4b")
    record_pair(conn, {"ornith": _cases(3, 6), "qwen4b": _cases(0, 6)}, DAY_AT - 5000)
    swept, why = sweeps.model(conn, reverify.served(conn)["repo"], runs.here(conn))
    assert swept["spec"] == "ornith" and why == ""


def test_the_newest_paired_run_decides_not_an_older_loss(conn, serve):
    serve("ornith", incumbent="qwen4b")
    record_pair(conn, {"ornith": _cases(1, 6), "qwen4b": _cases(3, 6)}, DAY_AT - 6000)
    record_pair(conn, {"ornith": _cases(4, 6), "qwen4b": _cases(2, 6)}, DAY_AT - 5000)
    swept, why = sweeps.model(conn, reverify.served(conn)["repo"], runs.here(conn))
    assert swept["spec"] == "ornith" and why == ""


def test_the_models_own_confounded_conversions_still_sweep_on_a_lane_that_does_not_convert(conn, serve):
    serve("ornith")
    lane_cuts(conn, 30, "glm")
    cases = [f"c{i}" for i in range(10)]
    old = DAY_AT - (binding.BINDING_WINDOW_DAYS + 5) * binding.DAY
    record(conn, "ornith", {c: "cut" for c in cases}, top=32768, sampling=LOW_SAMPLING, at=old)
    record(conn, VENDOR_SPEC, {c: "pass" for c in cases}, top=65536, sampling=VENDOR, at=old + 60)
    record(conn, "ornith", {c: "pass" for c in cases}, top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 3000)
    entry = sweeps.plan(conn, now=DAY_AT)[0]
    assert entry["evidence"]["binding"] is None and entry["evidence"]["cut"] == 10 and entry["skip"] == ""
