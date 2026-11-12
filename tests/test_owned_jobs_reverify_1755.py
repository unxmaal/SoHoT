"""A reverify job and the reverification that owns it commit together: a death between leaves neither, so the next trigger queues one. #1755, #1756."""
import pytest

from harness import job_state as js
from harness import paths, reverify, workqueue as wq
from harness import memory_store as ms
from tests import job_rows
from tests.test_reverify import (NOW, _latest, _queue_and_finish, cases, check, conn, on, powered,  # noqa: F401
                                 queued, upgraded)

pytestmark = pytest.mark.usefixtures("powered")


class Died(BaseException):
    """The process dies here; its connection closes with nothing more committed."""


def dies_after_add(calls=1):
    added = []

    def add(*a, **k):
        added.append(wq.add(*a, **k))
        if len(added) == calls:
            raise Died
        return added[-1]
    return add


@pytest.fixture
def reopen():
    opened = []

    def again(dead):
        dead.close()
        opened.append(ms.connect())
        return opened[-1]
    yield again
    for c in opened:
        c.close()


def test_a_death_between_the_job_and_its_reverification_queues_one_job_next_time(upgraded, reopen):
    with pytest.raises(Died):
        check(upgraded, add=dies_after_add())
    conn = reopen(upgraded)
    check(conn)
    [job] = queued(conn)
    assert _latest(conn)["job_id"] == int(job["id"])


def test_a_death_between_the_continuation_and_the_repoint_queues_one_continuation(upgraded, reopen):
    paused = _queue_and_finish(upgraded, cases("q3-4b", 3, total=3), rc=75, state=wq.PAUSED)
    with pytest.raises(Died):
        check(upgraded, now=NOW + 120, add=dies_after_add())
    conn = reopen(upgraded)
    check(conn, now=NOW + 120)
    [nxt] = [j for j in queued(conn) if j["id"] != paused["id"]]
    assert "--resume" in nxt["argv"] and _latest(conn)["job_id"] == int(nxt["id"])


def test_a_later_judge_that_raises_keeps_the_repoint(upgraded, reopen, monkeypatch):
    paused = _queue_and_finish(upgraded, cases("q3-4b", 3, total=3), rc=75, state=wq.PAUSED)
    first = _latest(upgraded)
    done = wq.add(["true"], cwd=str(paths.REPO), requested_by="test", conn=upgraded)
    job_rows.put({**done, "state": wq.DONE, "rc": 0}, conn=upgraded)
    upgraded.execute("INSERT INTO reverifications (lane, candidate_id, spec, incumbent, triggers, job_id, "
                     "machine_id, queued_at) SELECT 'web', candidate_id, spec, incumbent, triggers, ?, machine_id, "
                     "queued_at FROM reverifications WHERE id = ?", (int(done["id"]), first["id"]))
    upgraded.commit()

    def broke(*a, **k):
        raise RuntimeError("judge broke")
    judge = reverify.judge
    monkeypatch.setattr(reverify, "judge", broke)
    with pytest.raises(RuntimeError):
        check(upgraded, now=NOW + 120)
    monkeypatch.setattr(reverify, "judge", judge)
    conn = reopen(upgraded)
    check(conn, now=NOW + 180)
    [nxt] = [j for j in queued(conn) if j["id"] != paused["id"]]
    row = conn.execute("SELECT job_id FROM reverifications WHERE id = ?", (first["id"],)).fetchone()
    assert row["job_id"] == int(nxt["id"])


def test_an_owner_that_loses_keeps_no_job(conn):
    got = js.add_owned(conn, [(["true"], {"cwd": str(paths.REPO)})], lambda rows: None)
    assert got == (None, []) and wq.jobs(conn=conn) == []


def test_an_uncommitted_job_needs_the_callers_connection():
    with pytest.raises(ValueError, match="connection"):
        wq.add(["true"], commit=False)
