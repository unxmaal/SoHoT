"""Another machine's reverifications in a shared store are its own: never settled, resumed or read as this machine's lane (#1929)."""
import pytest

from harness import machine, reverify, workqueue as wq
from harness import memory_store as ms
from tests.test_reverify import (NOW, _latest, _queue_and_finish, cases, check, conn, on, powered,  # noqa: F401
                                 queued, upgraded)

pytestmark = pytest.mark.usefixtures("powered")

OTHER = {"hw_model": "Other1,1", "os": "Linux", "arch": "x86_64", "host": "b-host"}


def _other(conn) -> int:
    got = ms.remember_machine(conn, {**OTHER, "fingerprint": machine.fingerprint(*OTHER.values())})
    conn.commit()
    return got


def _give(conn, rv_id, mid) -> None:
    conn.execute("UPDATE reverifications SET machine_id = ? WHERE id = ?", (mid, int(rv_id)))
    conn.commit()


def _row(conn, rv_id) -> dict:
    return dict(conn.execute("SELECT * FROM reverifications WHERE id = ?", (int(rv_id),)).fetchone())


def test_another_machines_paused_rerun_is_not_resumed_into_this_machines_queue(upgraded):
    conn = upgraded
    paused = _queue_and_finish(conn, cases("q3-4b", 3, total=3), rc=75, state=wq.PAUSED)
    rv = _latest(conn)
    _give(conn, rv["id"], _other(conn))
    before = len(wq.jobs(conn=conn))
    resumed: list = []
    assert reverify.settle(conn, now=NOW + 120, resumed=resumed) == [] and resumed == []
    assert len(wq.jobs(conn=conn)) == before
    row = _row(conn, rv["id"])
    assert (row["outcome"], row["job_id"]) == ("", int(paused["id"]))


def test_another_machines_finished_rerun_is_left_for_it_to_judge(upgraded):
    conn = upgraded
    _queue_and_finish(conn, cases("q3-4b", 0))
    rv = _latest(conn)
    _give(conn, rv["id"], _other(conn))
    assert reverify.settle(conn, now=NOW + 120) == []
    assert _row(conn, rv["id"])["outcome"] == ""
    _give(conn, rv["id"], ms.machine_row(conn))
    assert [s["id"] for s in reverify.settle(conn, now=NOW + 120)] == [rv["id"]]


def test_another_machines_open_rerun_does_not_say_this_lane_is_queued(upgraded):
    conn = upgraded
    check(conn)
    rv = _latest(conn)
    assert check(conn)["planned"][0]["skip"].startswith("already queued")
    _give(conn, rv["id"], _other(conn))
    got = check(conn)
    assert got["planned"][0]["skip"] == "" and len(got["queued"]) == 1


def test_another_machines_flagged_rerun_neither_holds_nor_flags_this_machines_lane(upgraded):
    conn = upgraded
    _queue_and_finish(conn, cases("q3-4b", 0), failure_class="timeout")
    check(conn, now=NOW + 120)
    rv = _latest(conn)
    assert rv["outcome"] == reverify.FAILED
    assert reverify.flags(conn)["code"]["id"] == rv["id"]
    assert check(conn, now=NOW + 180, dry_run=True)["planned"][0]["skip"].startswith("flagged failed")
    _give(conn, rv["id"], _other(conn))
    assert "code" not in reverify.flags(conn)
    assert reverify._latest(conn, "code", rv["candidate_id"], settled=True) is None
    assert check(conn, now=NOW + 180, dry_run=True)["planned"][0]["skip"] == ""
