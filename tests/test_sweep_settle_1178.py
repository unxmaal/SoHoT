"""A sweep settles when its best value holds a timeout row, and a value whose rows never ran is unrun, not 0 of n (#1178)."""
import json

from harness import reasons, runs, sweeps, workqueue as wq
from tests.test_knob_sweeps import ENV, NOW, _SEQ, binding_budget, conn, queued, serving  # noqa: F401


def _store(conn, job_id, rows):
    rid = runs.record(conn, f"runs/r{next(_SEQ)}-code",
                      {"receipt": {"modality": "code"}, "environment": ENV, "specs": {"q3-4b": "q3-4b"},
                       "rows": rows}, at=NOW + 60)
    conn.execute("UPDATE runs SET job_id = ? WHERE id = ?", (int(job_id), rid))
    conn.commit()


def _rows(passed, total, failure="content_failed", seconds=1.0):
    return [{"candidate": "q3-4b", "case_id": f"c{i}", "passed": i < passed, "seconds": seconds,
             "failure_class": "" if i < passed else failure} for i in range(total)]


def finish(conn, by_value):
    for job in queued(conn):
        wq._write({**job, "state": wq.DONE, "rc": 0}, conn=conn)
    row = conn.execute("SELECT jobs FROM knob_sweeps ORDER BY id DESC").fetchone()
    for value, job_id in json.loads(row["jobs"]):
        if value in by_value:
            _store(conn, job_id, by_value[value])


def test_live_sweep_4_settles_and_leaves_out_the_values_the_gateway_refused(conn, serving):
    """Sweep 4: 2000 and 4000 stored 108 refused_by_gateway rows each; the best value's run had a timeout row."""
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    best = _rows(30, 40)
    best[-1]["failure_class"], best[-2]["failure_class"] = reasons.TIMEOUT, reasons.REFUSED_BY_GATEWAY
    finish(conn, {2000: _rows(0, 40, reasons.REFUSED_BY_GATEWAY, 0.0), 4000: _rows(0, 40, reasons.REFUSED_BY_GATEWAY, 0.0),
                  8000: best, 16384: _rows(29, 40, seconds=2.0), 32768: _rows(28, 40, seconds=4.0)})
    got = sweeps.check(conn, now=NOW + 120)
    row = dict(conn.execute("SELECT * FROM knob_sweeps ORDER BY id DESC").fetchone())
    assert row["outcome"] in (sweeps.CHOSEN, sweeps.UNINFORMATIVE)
    cost = json.loads(row["cost"])
    assert set(cost) == {"8000", "16384", "32768"}
    assert cost["16384"]["power"] is not None
    assert got["settled"][0]["id"] == row["id"]


def test_a_value_with_one_judged_row_among_refused_ones_still_counts(conn, serving):
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    mixed = _rows(1, 40, reasons.REFUSED_BY_GATEWAY)
    finish(conn, {2000: mixed, 8000: _rows(30, 40)})
    sweeps.check(conn, now=NOW + 120)
    cost = json.loads(conn.execute("SELECT cost FROM knob_sweeps ORDER BY id DESC").fetchone()["cost"])
    assert set(cost) == {"2000", "8000"}


def test_the_power_to_see_a_loss_reads_a_timeout_as_decide_pairs_it():
    """On a reply-budget axis a timeout is a verdict, as in decide's pairing, so it is a failed draw, not a dropped one."""
    from harness import paired
    timed = _rows(30, 40, reasons.TIMEOUT)
    failed = _rows(30, 40)
    cell = paired.pair(failed, _rows(29, 40), same_repeat=True, unjudged=paired.UNJUDGED_ON_A_TIMEOUT_AXIS)
    assert sweeps._power_to_see_a_loss(timed, cell, 0.05, 0.1) == sweeps._power_to_see_a_loss(failed, cell, 0.05, 0.1)
