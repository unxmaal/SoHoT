"""A knob sweep whose pending jobs are all cancelled settles as cancelled, not unrun (#1364)."""
import json

from harness import sweeps, workqueue as wq
from tests.test_knob_sweeps import NOW, binding_budget, conn, queued, serving  # noqa: F401


def test_a_sweep_whose_pending_jobs_are_cancelled_settles_as_cancelled(conn, serving):
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    jobs = queued(conn)
    assert jobs and all(j["state"] == wq.PENDING for j in jobs)
    for job in jobs:
        wq.cancel(job["id"], conn=conn)
    got = sweeps.settle(conn, now=NOW + 120)
    assert [(s["outcome"], s["detail"]) for s in got] == [(sweeps.CANCELLED, "every job was cancelled")]
    row = conn.execute("SELECT outcome, jobs FROM knob_sweeps ORDER BY id DESC").fetchone()
    assert row["outcome"] == sweeps.CANCELLED
    assert {wq.get(j, conn=conn)["state"] for _, j in json.loads(row["jobs"])} == {wq.CANCELLED}
