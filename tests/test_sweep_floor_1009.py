"""A sweep whose values all sit at the floor or ceiling chooses nothing, and a sweep only runs a model that passes in the lane (#1009)."""
import json

import pytest

from harness import knobs, reverify, sweeps, workqueue as wq
from harness import memory_store as ms
from tests.test_knob_sweeps import DAY, M, NOW, _finish, _settled, binding_budget, queued, record

LIVE_SECONDS = {2000: 533.493, 4000: 900.0, 8000: 1300.0, 16384: 1700.0, 32768: 2300.0, 65536: 2637.787}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "this_machine", lambda: dict(M))
    c = ms.connect(tmp_path / "d.db")
    ms.remember_machine(c, dict(M))
    yield c
    c.close()


@pytest.fixture
def serving(monkeypatch):
    def serve(spec="q3-4b", lane="code", cid=None):
        monkeypatch.setattr(reverify, "served", lambda conn: {lane: {
            "lane": lane, "spec": spec, "candidate_id": cid, "incumbent": "", "incumbent_id": None}})
    serve()
    return serve


def _rows(passed, total, seconds):
    return [{"case_id": f"c{i}", "passed": i < passed, "seconds": seconds} for i in range(total)]


def test_six_values_all_at_zero_choose_nothing():
    """The live sweep 1: every value 0 of 39, so the fastest won the tie and 2000 was 'chosen'."""
    values = knobs.KNOBS["reply_budget"].values
    chosen, table = sweeps.decide(values, {v: _rows(0, 39, LIVE_SECONDS[v] / 39) for v in values}, 0.05)
    assert chosen is None
    assert not any(r["tied"] or r["best"] for r in table.values())
    assert sweeps.flat(table) == "every value passed 0 of its cases"


def test_values_all_at_the_ceiling_choose_nothing():
    chosen, table = sweeps.decide([2000, 4000], {2000: _rows(20, 20, 1.0), 4000: _rows(20, 20, 2.0)}, 0.05)
    assert chosen is None and sweeps.flat(table) == "every value passed every case"


def test_the_best_value_carries_no_power_against_itself():
    chosen, table = sweeps.decide([2000, 4000], {2000: _rows(199, 200, 1.0), 4000: _rows(200, 200, 2.0)}, 0.05)
    assert table["4000"]["best"] and table["4000"]["power"] is None
    assert table["2000"]["power"] is not None


def test_a_settled_all_zero_sweep_is_uninformative_and_leaves_the_knob(conn, serving):
    binding_budget(conn)
    before = knobs.KNOBS["reply_budget"].default("code")
    sweeps.check(conn, now=NOW)
    _finish(conn, {v: (0, LIVE_SECONDS[v] / 39) for v in knobs.KNOBS["reply_budget"].values}, total=39)
    got = sweeps.check(conn, now=NOW + 120)
    row = _settled(conn)
    assert row["outcome"] == sweeps.UNINFORMATIVE and row["chosen"] == ""
    assert got["settled"][0]["chosen"] is None
    assert "chose nothing" in row["detail"] and f"still {before:g}" in row["detail"]
    assert "the best" not in row["detail"]
    assert knobs.KNOBS["reply_budget"].default("code") == before == 32768
    assert "swept already" not in sweeps.check(conn, now=NOW + 240)["planned"][0]["skip"]


def test_a_served_model_that_passes_nothing_and_no_other_model_queues_nothing(conn, serving):
    record(conn, "code", 0, 41, limit="max_tokens.code>32768")
    got = sweeps.check(conn, now=NOW)
    assert got["queued"] == [] and queued(conn) == []
    why = got["planned"][0]["skip"]
    assert "q3-4b passed 0 of 41" in why and "no model passes a case in code" in why
    assert "not swept" in sweeps.render(got)


def test_a_served_model_that_passes_nothing_sweeps_the_best_passing_model(conn, serving):
    record(conn, "code", 0, 41, limit="max_tokens.code>32768")
    record(conn, "code", 2, 39, spec="ornith", at=NOW - 2 * DAY)
    record(conn, "code", 5, 39, spec="ornith-think", at=NOW - 2 * DAY)
    record(conn, "code", 4, 4, spec="claude-code:claude-opus-5-5", at=NOW - 2 * DAY)
    got = sweeps.check(conn, now=NOW)
    p = got["planned"][0]
    assert p["spec"] == "ornith-think" and len(got["queued"]) == 1
    assert all("ornith-think" in a for a in p["argv"].values())
    assert "q3-4b passed 0 of 41" in p["model"] and "best passing (5 of 39" in p["model"]


def test_a_served_model_whose_reverify_failed_is_not_swept(conn, serving):
    binding_budget(conn)
    cid = conn.execute("SELECT id FROM candidates WHERE spec = 'q3-4b'").fetchone()["id"]
    serving(cid=cid)
    conn.execute("INSERT INTO reverifications (lane, candidate_id, spec, queued_at, settled_at, outcome, detail) "
                 "VALUES ('code', ?, 'q3-4b', ?, ?, ?, 'q3-4b passed 0 of 41 in run 470')",
                 (cid, NOW - DAY, NOW - DAY, reverify.FAILED))
    conn.commit()
    got = sweeps.check(conn, now=NOW)
    assert got["queued"] == [] and "q3-4b passed 0 of 41 in run 470" in got["planned"][0]["skip"]


def test_a_sweeps_own_passing_runs_do_not_make_a_model_sweepable(conn, serving):
    record(conn, "code", 0, 10, limit="max_tokens.code>32768")
    job = wq.add(["true"], title="sweep", requested_by=sweeps.REQUESTED_BY, conn=conn)
    record(conn, "code", 3, 10, job_id=job["id"], at=NOW - DAY / 2)
    got = sweeps.check(conn, now=NOW)
    assert got["queued"] == [] and "q3-4b passed 0 of 10" in got["planned"][0]["skip"]


def _live_row(conn, cost, outcome=sweeps.CHOSEN, chosen="2000"):
    conn.execute("INSERT INTO knob_sweeps (knob, lane, spec, jobs, queued_at, settled_at, outcome, chosen, cost, "
                 "detail) VALUES ('reply_budget', 'repo', 'q3-4b', '[]', ?, ?, ?, ?, ?, 'chose 2000')",
                 (NOW, NOW, outcome, chosen, json.dumps(cost)))
    conn.commit()


def test_schema_78_refiles_a_chosen_sweep_whose_values_all_passed_nothing(conn):
    zero = {str(v): {"passed": 0, "n": 39, "seconds": s, "power": 1.0 if v == 2000 else 0.0, "tied": v == 2000,
                     "best": v == 2000, "underpowered": v != 2000} for v, s in LIVE_SECONDS.items()}
    real = {"2000": {"passed": 30, "n": 39, "seconds": 1.0, "tied": True, "best": False},
            "4000": {"passed": 31, "n": 39, "seconds": 2.0, "tied": True, "best": True}}
    _live_row(conn, zero)
    _live_row(conn, real)
    from harness.memory_store.migrations import v78
    v78.data(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM knob_sweeps ORDER BY id")]
    assert rows[0]["outcome"] == sweeps.UNINFORMATIVE and rows[0]["chosen"] == ""
    assert "chose nothing" in rows[0]["detail"] and "still 32768" in rows[0]["detail"]
    cost = json.loads(rows[0]["cost"])
    assert cost["2000"]["power"] is None and not any(r["best"] or r["tied"] for r in cost.values())
    assert rows[1]["outcome"] == sweeps.CHOSEN and rows[1]["chosen"] == "2000"
    assert sweeps.refile(conn) == 0
