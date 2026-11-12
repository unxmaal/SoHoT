"""A knob sweep's jobs and its row commit together: a death between leaves neither, so the next trigger queues one set. #1755, #1756."""
import json

import pytest

from harness import sweeps, workqueue as wq
from harness import memory_store as ms
from tests.test_knob_sweeps import NOW, binding_budget, conn, queued, record, serving  # noqa: F401
from tests.test_owned_jobs_reverify_1755 import Died, dies_after_add, reopen  # noqa: F401


def test_a_death_between_the_jobs_and_their_sweep_queues_one_set_next_time(conn, serving, reopen):
    binding_budget(conn)
    [entry] = [p for p in sweeps.plan(conn, now=NOW) if not p["skip"]]
    with pytest.raises(Died):
        sweeps.check(conn, now=NOW, add=dies_after_add(len(entry["argv"])))
    c = reopen(conn)
    [sw] = sweeps.check(c, now=NOW)["queued"]
    assert sorted(int(j["id"]) for j in queued(c)) == sorted(j for _, j in sw["jobs"])
    assert len(sw["jobs"]) == len(entry["argv"])


def test_a_death_between_a_continuation_and_its_sweep_queues_one_continuation(conn, serving, reopen):
    binding_budget(conn)
    [sw] = sweeps.check(conn, now=NOW)["queued"]
    value, paused = sw["jobs"][0]
    conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.PAUSED, paused))
    conn.commit()
    with pytest.raises(Died):
        sweeps.settle(conn, now=NOW + 120, add=dies_after_add())
    c = reopen(conn)
    sweeps.settle(c, now=NOW + 120)
    before = {j for _, j in sw["jobs"]}
    [nxt] = [int(j["id"]) for j in queued(c) if int(j["id"]) not in before]
    row = c.execute("SELECT jobs FROM knob_sweeps WHERE id = ?", (sw["sweep"],)).fetchone()
    assert json.loads(row["jobs"])[0] == [value, nxt]
