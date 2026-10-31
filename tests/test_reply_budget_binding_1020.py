"""A reply-budget sweep asks the stored runs first, counts only cuts that pass with more room, and queues for the night (#1020)."""
import json
from datetime import datetime

import pytest

from harness import convertible, heartbeat, reverify, runs, sweeps, workqueue as wq
from harness import memory_store as ms
from tests.test_knob_sweeps import ENV, M, queued
from tests import conftest

DAY_AT = datetime(2027, 1, 15, 9, 30).timestamp()
LOW_SAMPLING = {"repo": {"temperature": 0.2}}
VENDOR = {"repo": {"temperature": 1.0, "top_p": 0.95, "top_k": 20}}
VENDOR_SPEC = "ornith,enable_thinking=true,temperature=1.0,top_p=0.95,top_k=20"
_SEQ = iter(range(1, 10_000))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    conftest.stand_in_machine(monkeypatch, M)
    monkeypatch.setattr(heartbeat, "discover_hours", lambda: [21])
    monkeypatch.setattr(reverify, "served", lambda c: {"repo": {
        "lane": "repo", "spec": "ornith", "candidate_id": None, "incumbent": "", "incumbent_id": None}})
    c = ms.connect(tmp_path / "d.db")
    ms.remember_machine(c, dict(M))
    yield c
    c.close()


def _row(spec, case, outcome, top, ladder=(), seconds=1.0):
    """outcome: 'pass', 'wrong' or 'cut' at the run's top budget; ladder lists the rungs below top a case was cut at."""
    cut = outcome == "cut"
    tries = [{"max_tokens": b, "passed": False, "failure_class": convertible.CUT} for b in ladder]
    if ladder:
        tries.append({"max_tokens": top, "passed": outcome == "pass",
                      "failure_class": convertible.CUT if cut else ("" if outcome == "pass" else "content_failed")})
    return {"candidate": spec, "case_id": case, "passed": outcome == "pass", "seconds": seconds,
            "failure_class": convertible.CUT if cut else ("" if outcome == "pass" else "content_failed"),
            "limit": f"max_tokens.repo>{top}" if cut else "", "attempts": tries,
            "metrics": {"resolved": float(outcome == "pass")}}


def record(conn, spec, outcomes, *, top, sampling, ladder=(), at=DAY_AT - 3600, seconds=1.0):
    """outcomes: case -> 'pass'|'wrong'|'cut', or (outcome, rungs cut below top) for a laddered case."""
    rows = []
    for case, got in outcomes.items():
        outcome, rungs = got if isinstance(got, tuple) else (got, ())
        rows.append(_row(spec, case, outcome, top, rungs, seconds))
    receipt = {"modality": "repo", "max_tokens": top, "budget_ladder": list(ladder), "sampling": sampling}
    return runs.record(conn, f"runs/r{next(_SEQ)}-repo",
                       {"receipt": receipt, "environment": ENV, "specs": {spec: spec}, "rows": rows}, at=at)


def runs_472_474(conn):
    """The live pair: 21 cut at 32768 under default sampling; at 65536 with vendor sampling 17 finish wrong, 4 cut again."""
    cases = [f"c{i}" for i in range(39)]
    low = {c: "cut" for c in cases[:21]} | {c: "pass" for c in cases[21:23]} | {c: "wrong" for c in cases[23:]}
    high = ({c: ("wrong", (32768,)) for c in cases[:17]} | {c: ("cut", (32768,)) for c in cases[17:21]}
            | {c: "pass" for c in cases[21:26]} | {c: "wrong" for c in cases[26:]})
    return (record(conn, "ornith", low, top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 7200),
            record(conn, VENDOR_SPEC, high, top=65536, sampling=VENDOR, ladder=(32768, 65536)))


def test_runs_472_and_474_queue_nothing_and_say_the_budget_is_not_binding(conn):
    low, high = runs_472_474(conn)
    got = sweeps.check(conn, now=DAY_AT)
    assert got["queued"] == [] and queued(conn) == []
    skip = got["planned"][0]["skip"]
    assert "not binding: 0 of 21 cut replies pass at 65536 (confounded: sampling differs)" in skip
    assert f"runs {low} and {high}, 17 finished wrong, 4 cut again" in skip
    assert "not swept, not binding" in sweeps.render(got)
    row = dict(conn.execute("SELECT * FROM knob_sweeps").fetchone())
    assert row["outcome"] == sweeps.NOT_BINDING and row["jobs"] == "[]" and row["settled_at"] == DAY_AT
    assert json.loads(row["cost"])["cut"] == 21 and json.loads(row["trigger"])["convertible"] == 0
    sweeps.check(conn, now=DAY_AT + 60)
    assert conn.execute("SELECT COUNT(*) FROM knob_sweeps").fetchone()[0] == 1


def test_the_ladder_of_the_swept_spec_is_the_unconfounded_answer(conn, monkeypatch):
    """Live: the swept spec is run 474's, whose own ladder retried 13 cut replies at 65536 with nothing else changed."""
    monkeypatch.setattr(reverify, "served", lambda c: {"repo": {
        "lane": "repo", "spec": VENDOR_SPEC, "candidate_id": None, "incumbent": "", "incumbent_id": None}})
    low, high = runs_472_474(conn)
    skip = sweeps.check(conn, now=DAY_AT)["planned"][0]["skip"]
    assert skip.startswith("not binding: 0 of 21 cut replies pass at 65536 (same settings)")
    assert f"run {high}'s ladder" in skip


def test_cut_replies_that_pass_with_more_room_queue_a_sweep_for_the_night(conn):
    cases = [f"c{i}" for i in range(20)]
    record(conn, "ornith", {c: "cut" for c in cases[:10]} | {c: "pass" for c in cases[10:]},
           top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 7200)
    record(conn, "ornith", {c: "pass" for c in cases[:4]} | {c: "wrong" for c in cases[4:10]}
           | {c: "pass" for c in cases[10:]}, top=65536, sampling=LOW_SAMPLING)
    got = sweeps.check(conn, now=DAY_AT)
    assert got["planned"][0]["skip"] == ""
    assert got["planned"][0]["evidence"]["detail"].startswith("binding: 4 of 10 cut replies pass at 65536")
    assert got["planned"][0]["trigger"]["convertible"] == 4
    start, _ = wq.night_window(DAY_AT)
    jobs = queued(conn)
    assert len(jobs) == 6 and start > DAY_AT
    assert {j["not_before"] for j in jobs} == {datetime.fromtimestamp(start).isoformat(timespec="seconds")}
    assert not wq.ready(conn=conn, now=DAY_AT) and len(wq.ready(conn=conn, now=start)) == 6
    assert "to start" in sweeps.render(got)


def test_a_sweep_projected_past_the_night_is_refused_with_the_projection(conn):
    cases = [f"c{i}" for i in range(20)]
    record(conn, "ornith", {c: "cut" for c in cases[:10]} | {c: "pass" for c in cases[10:]},
           top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 7200, seconds=1000.0)
    got = sweeps.check(conn, now=DAY_AT)
    assert got["queued"] == [] and queued(conn) == []
    skip = got["planned"][0]["skip"]
    assert skip.startswith("projected ") and "over the night's 11h 00m (21:00 to 08:00)" in skip
    assert got["planned"][0]["projected_s"] > 11 * 3600


def test_conversions_under_other_sampling_cannot_tell_budget_from_sampling_and_still_sweep(conn):
    cases = [f"c{i}" for i in range(20)]
    record(conn, "ornith", {c: "cut" for c in cases[:10]} | {c: "pass" for c in cases[10:]},
           top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 7200)
    record(conn, VENDOR_SPEC, {c: "pass" for c in cases}, top=65536, sampling=VENDOR)
    got = sweeps.check(conn, now=DAY_AT)
    assert got["planned"][0]["evidence"]["binding"] is None
    assert "unknown: 10 of 10 cut replies pass at 65536 (confounded: sampling differs)" in (
        got["planned"][0]["evidence"]["detail"])
    assert len(queued(conn)) == 6


def test_a_new_run_showing_conversions_reopens_a_knob_once_found_not_binding(conn):
    runs_472_474(conn)
    sweeps.check(conn, now=DAY_AT)
    cases = [f"c{i}" for i in range(39)]
    record(conn, "ornith", {c: "pass" for c in cases[:5]} | {c: "wrong" for c in cases[5:]},
           top=65536, sampling=LOW_SAMPLING, at=DAY_AT + 60)
    got = sweeps.check(conn, now=DAY_AT + 120)
    assert got["planned"][0]["evidence"]["detail"].startswith("binding: 5 of 21 cut replies pass at 65536")
    assert len(queued(conn)) == 6


def test_no_stored_run_with_more_room_still_sweeps(conn):
    cases = [f"c{i}" for i in range(20)]
    record(conn, "ornith", {c: "cut" for c in cases[:10]} | {c: "pass" for c in cases[10:]},
           top=32768, sampling=LOW_SAMPLING)
    got = sweeps.check(conn, now=DAY_AT)
    assert got["planned"][0]["evidence"]["binding"] is None
    assert "no stored run of ornith in repo gave a reply cut at 32768 more room" in sweeps.render(got)
    assert len(queued(conn)) == 6


def test_the_night_window_runs_from_the_discover_hour_to_the_day_start(monkeypatch):
    monkeypatch.setattr(heartbeat, "discover_hours", lambda: [21])
    start, end = wq.night_window(DAY_AT)
    assert datetime.fromtimestamp(start) == datetime(2027, 1, 15, 21, 0)
    assert datetime.fromtimestamp(end) == datetime(2027, 1, 16, 8, 0)
    late = datetime(2027, 1, 15, 23, 15).timestamp()
    assert wq.night_window(late) == (late, datetime(2027, 1, 16, 8, 0).timestamp())
