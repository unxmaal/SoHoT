"""Readers of a shared store see only this machine's rows: knob sweeps settled and listed, a sweep's step jobs, the jobs a residency trace replays (#1771)."""
import argparse
import json

from harness import machine, residency_trace, sweeps
from harness import memory_store as ms
from harness import workqueue as wq
from harness.commands import loop_steps as steps
from tests.test_knob_sweeps import NOW, binding_budget, conn, record, serving  # noqa: F401

OTHER = {"hw_model": "Other1,1", "os": "Linux", "arch": "x86_64", "host": "b-host"}


def _other(conn) -> int:
    got = ms.remember_machine(conn, {**OTHER, "fingerprint": machine.fingerprint(*OTHER.values())})
    conn.commit()
    return got


def _give(conn, table, row_id, mid) -> None:
    conn.execute(f"UPDATE {table} SET machine_id = ? WHERE id = ?", (mid, int(row_id)))
    conn.commit()


def _open_sweep(conn) -> dict:
    binding_budget(conn)
    assert len(sweeps.check(conn, now=NOW)["queued"]) == 1
    return dict(conn.execute("SELECT * FROM knob_sweeps ORDER BY id DESC").fetchone())


def _finish(conn, sw, paused=None) -> None:
    for i, (value, job_id) in enumerate(json.loads(sw["jobs"])):
        conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.PAUSED if i == paused else wq.DONE, int(job_id)))
        record(conn, "code", 19 if value == 2000 else 20, 20, at=NOW + 60, job_id=job_id)
    conn.commit()


def test_another_machines_paused_sweep_job_is_not_resumed_into_this_machines_queue(conn, serving):
    sw = _open_sweep(conn)
    _finish(conn, sw, paused=1)
    _give(conn, "knob_sweeps", sw["id"], _other(conn))
    before = len(wq.jobs(conn=conn))
    resumed: list = []
    assert sweeps.settle(conn, now=NOW + 120, resumed=resumed) == [] and resumed == []
    assert len(wq.jobs(conn=conn)) == before
    row = conn.execute("SELECT outcome, jobs FROM knob_sweeps WHERE id = ?", (sw["id"],)).fetchone()
    assert (row["outcome"], row["jobs"]) == (sweeps.OPEN, sw["jobs"])


def test_another_machines_finished_sweep_is_left_for_it_to_judge(conn, serving):
    sw = _open_sweep(conn)
    _finish(conn, sw)
    _give(conn, "knob_sweeps", sw["id"], _other(conn))
    assert sweeps.settle(conn, now=NOW + 120) == []
    assert conn.execute("SELECT outcome FROM knob_sweeps WHERE id = ?", (sw["id"],)).fetchone()[0] == sweeps.OPEN
    _give(conn, "knob_sweeps", sw["id"], ms.machine_row(conn))
    assert [s["id"] for s in sweeps.settle(conn, now=NOW + 120)] == [sw["id"]]


def test_the_decisions_listed_are_this_machines(conn, serving):
    sw = _open_sweep(conn)
    _finish(conn, sw)
    assert [s["id"] for s in sweeps.settle(conn, now=NOW + 120)] == [sw["id"]]
    assert [d["knob"] for d in sweeps.decided(conn)] == [sw["knob"]]
    _give(conn, "knob_sweeps", sw["id"], _other(conn))
    assert sweeps.decided(conn) == []


def _ns():
    return argparse.Namespace(lane="", top=None, budget_gib=None, repeat=None, ceiling_h=11.0, effect=None,
                              power_budget_min=30.0, run=True, loop=True, jobs=True)


def test_another_machines_sweep_step_neither_blocks_nor_stands_in_for_this_machines(conn):
    cycle = "1700000000"
    theirs = steps.queue("repair", cycle, _ns(), conn=conn)
    assert steps.live(conn) == {cycle: wq.label(theirs["id"])}
    _give(conn, "jobs", theirs["id"], _other(conn))
    assert steps.live(conn) == {}
    mine = steps.queue("repair", cycle, _ns(), conn=conn)
    assert not mine.get("existed") and int(mine["id"]) != int(theirs["id"])
    assert steps._jobs_of(conn, cycle) == [(int(mine["id"]), "repair", wq.PENDING)]


def test_a_residency_trace_replays_only_the_jobs_this_machine_ran(conn):
    here, other = ms.machine_row(conn), _other(conn)
    for model, mid in (("Mine-Q4", here), ("Theirs-Q4", other)):
        job = wq.add(["uv", "run", "python", "-m", "evals.run", "--candidates", f"llamacpp:{model}"],
                     requested_by="test", conn=conn)
        conn.execute("UPDATE jobs SET state = ?, started_at = ?, finished_at = ?, machine_id = ? WHERE id = ?",
                     (wq.DONE, NOW, NOW + 60, mid, int(job["id"])))
    conn.commit()
    got = residency_trace.jobs(conn, NOW - 10, NOW + 100, {})
    assert [g[2] for g in got] == ["Mine-Q4"]
