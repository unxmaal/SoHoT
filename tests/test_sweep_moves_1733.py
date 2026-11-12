"""A knob sweep moves only through sweeps.MOVES by compare-and-swap: paused and deleted jobs are named, a settled sweep leaves only by refile (#1733)."""
import json

import pytest

from harness import knobs, sweeps, workqueue as wq
from harness import memory_store as ms
from tests.test_knob_sweeps import NOW, binding_budget, conn, record, serving  # noqa: F401

VALUES = knobs.KNOBS["reply_budget"].values


def _open(conn):
    binding_budget(conn)
    got = sweeps.check(conn, now=NOW)
    assert len(got["queued"]) == 1
    return _row(conn)


def _row(conn, sweep_id=None):
    if sweep_id is None:
        return dict(conn.execute("SELECT * FROM knob_sweeps ORDER BY id DESC").fetchone())
    return dict(conn.execute("SELECT * FROM knob_sweeps WHERE id = ?", (sweep_id,)).fetchone())


def _set(conn, job_id, state):
    conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (state, int(job_id)))
    conn.commit()


def _finish_all(conn, sw, state=wq.DONE):
    for value, job_id in json.loads(sw["jobs"]):
        _set(conn, job_id, state)
        record(conn, "code", 19 if value == 2000 else 20, 20, at=NOW + 60, job_id=job_id)


def test_a_paused_job_is_resumed_and_the_sweep_is_not_judged_on_its_partial_run(conn, serving):
    sw = _open(conn)
    jobs = json.loads(sw["jobs"])
    _finish_all(conn, sw)
    paused_value, paused = jobs[2]
    _set(conn, paused, wq.PAUSED)
    resumed = []
    assert sweeps.settle(conn, now=NOW + 120, resumed=resumed) == []
    row = _row(conn, sw["id"])
    assert row["outcome"] == sweeps.OPEN and row["settled_at"] is None
    assert [(r["value"], int(r["paused"])) for r in resumed] == [(paused_value, paused)]
    nxt = wq.get(resumed[0]["job"], conn=conn)
    assert nxt["state"] == wq.PENDING and "--resume" in nxt["argv"] and "--out" in nxt["argv"]
    assert json.loads(row["jobs"])[2] == [paused_value, int(nxt["id"])]
    assert [j for _, j in json.loads(row["jobs"])][:2] == [j for _, j in jobs[:2]]


def test_a_dry_run_leaves_a_paused_job_paused(conn, serving):
    sw = _open(conn)
    _finish_all(conn, sw)
    _set(conn, json.loads(sw["jobs"])[0][1], wq.PAUSED)
    before = len(wq.jobs(conn=conn))
    assert sweeps.check(conn, now=NOW + 120, dry_run=True)["settled"] == []
    assert len(wq.jobs(conn=conn)) == before and _row(conn, sw["id"])["jobs"] == sw["jobs"]


def test_every_job_deleted_settles_cancelled_by_name(conn, serving):
    sw = _open(conn)
    conn.execute("DELETE FROM jobs")
    conn.commit()
    got = sweeps.settle(conn, now=NOW + 120)
    assert [(s["outcome"], s["detail"]) for s in got] == [(sweeps.CANCELLED, "every job was deleted")]
    assert _row(conn, sw["id"])["outcome"] == sweeps.CANCELLED


def test_deleted_and_cancelled_jobs_together_settle_cancelled(conn, serving):
    sw = _open(conn)
    jobs = json.loads(sw["jobs"])
    conn.execute("DELETE FROM jobs WHERE id = ?", (jobs[0][1],))
    for _, job_id in jobs[1:]:
        _set(conn, job_id, wq.CANCELLED)
    got = sweeps.settle(conn, now=NOW + 120)
    assert [(s["outcome"], s["detail"]) for s in got] == [(sweeps.CANCELLED, "every job was cancelled or deleted")]


def test_a_job_in_a_state_the_sweep_does_not_know_keeps_it_open(conn, serving):
    sw = _open(conn)
    _finish_all(conn, sw)
    _set(conn, json.loads(sw["jobs"])[0][1], "limbo")
    assert sweeps.settle(conn, now=NOW + 120) == []
    assert _row(conn, sw["id"])["outcome"] == sweeps.OPEN


def test_a_not_binding_finding_is_never_stacked_on_an_open_sweep(conn, serving):
    sw = _open(conn)
    entry = {k: sw[k] for k in ("knob", "lane", "spec", "candidate_id", "machine_id")}
    entry.update(trigger={}, skip="not binding: 0 of 13 cut replies pass",
                 evidence={"lane": True, "cut": 13, "passed": 0, "where": ["run 1"]})
    assert sweeps._not_binding(conn, entry, NOW + 60) is None
    assert conn.execute("SELECT COUNT(*) FROM knob_sweeps").fetchone()[0] == 1
    assert "already queued" in sweeps.check(conn, now=NOW + 90)["planned"][0]["skip"]
    _finish_all(conn, sw)
    sweeps.settle(conn, now=NOW + 120)
    assert sweeps._not_binding(conn, entry, NOW + 180)["sweep"] > sw["id"]
    assert sweeps._not_binding(conn, entry, NOW + 240) is None


def test_a_chosen_sweep_before_a_not_binding_finding_still_counts_as_swept(conn, serving):
    sw = _open(conn)
    _finish_all(conn, sw)
    sweeps.settle(conn, now=NOW + 120)
    assert _row(conn, sw["id"])["outcome"] == sweeps.CHOSEN
    entry = {k: sw[k] for k in ("knob", "lane", "spec", "candidate_id", "machine_id")}
    entry.update(trigger={}, skip="not binding", evidence={"lane": True, "cut": 20, "passed": 0, "where": []})
    assert sweeps._not_binding(conn, entry, NOW + 180) is not None
    assert "swept already" in sweeps.check(conn, now=NOW + 240)["planned"][0]["skip"]


def test_a_second_settle_racing_the_same_sweep_loses(conn, serving, monkeypatch):
    sw = _open(conn)
    _finish_all(conn, sw)
    other = ms.connect()
    judge = sweeps.judge

    def raced(c, s):
        if c is conn:
            sweeps.settle(other, now=NOW + 100)
        return judge(c, s)
    monkeypatch.setattr(sweeps, "judge", raced)
    try:
        assert sweeps.settle(conn, now=NOW + 120) == []
    finally:
        other.close()
    row = _row(conn, sw["id"])
    assert row["outcome"] == sweeps.CHOSEN and row["settled_at"] == NOW + 100


def test_a_second_writer_opening_the_same_sweep_loses_and_keeps_no_job(conn, serving, monkeypatch):
    from harness import item_lease
    binding_budget(conn)
    entry = next(p for p in sweeps.plan(conn, now=NOW) if not p["skip"])
    key = sweeps._LEDGER + json.dumps([entry["knob"], entry["lane"], entry["spec"], entry["machine_id"]])
    stale = item_lease._version(conn, key)
    other = ms.connect()
    try:
        first = sweeps._queue(other, entry, NOW, wq.add)
    finally:
        other.close()
    # This writer read the ledger before the other committed, and did not see its open sweep.
    real_open, real_version = sweeps._open, item_lease._version
    monkeypatch.setattr(sweeps, "_open", lambda c, sw: None if c is conn else real_open(c, sw))
    monkeypatch.setattr(item_lease, "_version", lambda c, k: stale if c is conn and k == key else real_version(c, k))
    assert sweeps._queue(conn, entry, NOW, wq.add) is None
    rows = conn.execute("SELECT id, outcome FROM knob_sweeps").fetchall()
    assert [(r["id"], r["outcome"]) for r in rows] == [(first["sweep"], sweeps.OPEN)]
    assert {int(j["id"]) for j in wq.jobs(conn=conn)} == {j for _, j in first["jobs"]}


def _chosen(conn, cost, outcome=sweeps.CHOSEN):
    conn.execute("INSERT INTO knob_sweeps (knob, lane, spec, jobs, queued_at, settled_at, outcome, chosen, cost, "
                 "detail) VALUES ('reply_budget', 'repo', 'q3-4b', '[]', ?, ?, ?, '2000', ?, 'chose 2000')",
                 (NOW, NOW, outcome, json.dumps(cost)))
    conn.commit()
    return _row(conn)


ZERO = {str(v): {"passed": 0, "n": 39, "seconds": 1.0, "power": 1.0, "tied": v == 2000, "best": v == 2000}
        for v in VALUES}


def test_refile_is_the_one_named_move_out_of_a_settled_sweep(conn):
    sw = _chosen(conn, ZERO)
    left = _chosen(conn, ZERO, outcome=sweeps.UNINFORMATIVE)
    assert sweeps.refile(conn) == 1
    row = _row(conn, sw["id"])
    assert row["outcome"] == sweeps.UNINFORMATIVE and row["chosen"] == ""
    assert row["detail"].startswith("refiled from chosen 2000 (#1009): ")
    assert _row(conn, left["id"])["detail"] == "chose 2000"
    assert sweeps.refile(conn) == 0


@pytest.mark.parametrize("frm,to,reason", [
    (sweeps.CHOSEN, sweeps.OPEN, sweeps.REFILED),
    (sweeps.UNINFORMATIVE, sweeps.CHOSEN, sweeps.JUDGED),
    (sweeps.CHOSEN, sweeps.UNINFORMATIVE, sweeps.JUDGED),
    (sweeps.CANCELLED, sweeps.UNRUN, sweeps.JUDGED),
    (sweeps.OPEN, sweeps.NOT_BINDING, sweeps.JUDGED),
    (None, sweeps.CHOSEN, sweeps.QUEUED),
])
def test_a_settled_sweep_is_never_edited_but_by_refile(conn, frm, to, reason):
    sw = _chosen(conn, ZERO, outcome=sweeps.OPEN if frm is None else frm)
    with pytest.raises(sweeps.IllegalMove):
        sweeps._move(conn, sw, frm, to, reason, detail="x")
    assert _row(conn, sw["id"])["detail"] == "chose 2000"


def test_a_refile_racing_a_settled_rewrite_loses(conn):
    sw = _chosen(conn, ZERO)
    conn.execute("UPDATE knob_sweeps SET outcome = ? WHERE id = ?", (sweeps.UNINFORMATIVE, sw["id"]))
    conn.commit()
    assert sweeps._move(conn, sw, sweeps.CHOSEN, sweeps.UNINFORMATIVE, sweeps.REFILED, detail="late") is None
    assert _row(conn, sw["id"])["detail"] == "chose 2000"
