"""A paused job's continuation is queued on this release, not the one that built it; one that cannot be queued is skipped by name. #2070."""
import json

import pytest

from harness import job_release, reverify, store_copy, workqueue as wq
from harness import memory_store as ms
from tests.test_job_release_1788 import release
from tests.test_reverify import NOW, _latest, _queue_and_finish, cases, conn, on, powered, upgraded  # noqa: F401

pytestmark = pytest.mark.usefixtures("powered")


@pytest.fixture
def deployed(monkeypatch):
    old, new = release("108-aaaaaaaaaaaa", ms.SCHEMA_VERSION - 1), release("113-bbbbbbbbbbbb")
    monkeypatch.setattr(job_release, "here", lambda: new)
    return old, new


def _built_by(conn, job_id, old, cwd=None):
    job = wq.get(job_id, conn=conn)
    argv = [str(old / ".venv" / "bin" / "python"), *job["argv"][1:]]
    conn.execute("UPDATE jobs SET cwd = ?, argv = ? WHERE id = ?", (str(cwd or old), json.dumps(argv), int(job_id)))
    conn.commit()


def _twin(conn, rv_id, old, cwd=None) -> int:
    """A second open reverification on its own paused job built by `old`."""
    src = wq.get(_row(conn, rv_id)["job_id"], conn=conn)
    job = wq.add(src["argv"], conn=conn)
    conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.PAUSED, int(job["id"])))
    _built_by(conn, job["id"], old, cwd)
    cols = [c for c in store_copy.columns(conn, "reverifications") if c != "id"]
    cur = conn.execute(f"INSERT INTO reverifications ({', '.join(cols)}) SELECT {', '.join(cols)} "
                       "FROM reverifications WHERE id = ?", (int(rv_id),))
    conn.execute("UPDATE reverifications SET job_id = ? WHERE id = ?", (int(job["id"]), cur.lastrowid))
    conn.commit()
    return cur.lastrowid


def _row(conn, rv_id) -> dict:
    return dict(conn.execute("SELECT * FROM reverifications WHERE id = ?", (int(rv_id),)).fetchone())


def test_a_paused_rerun_built_by_an_older_release_continues_on_this_one(upgraded, deployed):
    conn, (old, new) = upgraded, deployed
    paused = _queue_and_finish(conn, cases("q3-4b", 3, total=10), rc=75, state=wq.PAUSED)
    _built_by(conn, paused["id"], old)
    resumed: list = []
    reverify.settle(conn, now=NOW + 120, resumed=resumed)
    [got] = resumed
    nxt = wq.get(got["job"], conn=conn)
    assert nxt["cwd"] == str(new) and nxt["argv"][0] == str(new / ".venv" / "bin" / "python")
    assert "--resume" in nxt["argv"] and str(old) not in " ".join(nxt["argv"])
    assert _latest(conn)["job_id"] == int(got["job"])


def test_a_continuation_that_cannot_be_queued_is_skipped_and_the_rest_still_resume(upgraded, deployed):
    conn, (old, new) = upgraded, deployed
    paused = _queue_and_finish(conn, cases("q3-4b", 3, total=10), rc=75, state=wq.PAUSED)
    gone = old / "only-in-108"
    gone.mkdir()
    first = _latest(conn)["id"]
    second = _twin(conn, first, old)
    _built_by(conn, paused["id"], old, cwd=gone)
    resumed: list = []
    reverify.settle(conn, now=NOW + 120, resumed=resumed)
    refused, ok = resumed
    assert (refused["id"], refused["job"]) == (first, None) and "only-in-108" in refused["refused"]
    assert ok["id"] == second and wq.get(ok["job"], conn=conn)["cwd"] == str(new)
    row = _row(conn, first)
    assert (row["outcome"], row["job_id"]) == ("", int(paused["id"]))

