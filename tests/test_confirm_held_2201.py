"""#2201: a held holdout win whose weights are gone is refetched once for its confirm, a refusal that will not change queues no successor, one confirm is live per verdict."""
import json

import pytest
from test_confirm_resume_1357 import SPLIT, _fake_eval, _held, _in_process, conn  # noqa: F401
from test_refetch_2161 import GIB, _downloaded

from evals import watch
from harness import adopt, disk, fetching, paths, refetch, test_weights, workqueue
from harness import memory_store as ms
from harness.commands import adopt as adopt_cmd
from harness.commands import measure as measure_cmd

REPO = "org/x"
REAL_FETCH = test_weights.fetched


@pytest.fixture
def held(conn, tmp_path, monkeypatch):
    """A held win whose weights were downloaded after it and deleted since: the guard refuses a plain second download."""
    fetched = []
    monkeypatch.setattr(test_weights, "fetched", REAL_FETCH)
    monkeypatch.setattr(fetching, "download", lambda repo, **k: fetched.append(repo) or f"/x/{repo}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    monkeypatch.setattr(fetching, "disk_floor", lambda: 0)
    vid = _held(conn, tmp_path, monkeypatch)
    conn.execute("UPDATE verdicts SET decided_at = decided_at - 7200 WHERE id = ?", (vid,))
    conn.execute("DELETE FROM jobs")
    conn.commit()
    ms.set_size(conn, REPO, GIB)
    _downloaded(conn, REPO, gib=1, ago_s=3600)
    return conn, vid, fetched


def _ensure(conn, via):
    return fetching.ensure(conn, REPO, free=900 * GIB, floor=0, via=via)


def test_a_held_win_with_its_weights_deleted_is_refetched_once_and_reaches_a_confirm_verdict(held, monkeypatch):
    conn, vid, fetched = held
    seen = {}
    _fake_eval(monkeypatch, seen)
    assert measure_cmd.confirm_job(vid) == 0
    assert fetched == [REPO]
    row = conn.execute("SELECT outcome, detail FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()
    assert row["outcome"] == "measured" and "confirmed on 10 dev case(s)" in row["detail"], row["detail"]


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/refetch.py:refusal")
def test_the_leave_is_one_refetch_for_that_held_verdict_and_no_other_fetch(held):
    conn, vid, fetched = held
    assert "so it is not downloaded again" in _ensure(conn, "measure")
    assert "so it is not downloaded again" in _ensure(conn, f"confirm {vid + 1}")
    assert fetched == []
    assert _ensure(conn, f"confirm {vid}") == "" and fetched == [REPO]
    _downloaded(conn, REPO, gib=1, ago_s=60)
    assert "so it is not downloaded again" in _ensure(conn, f"confirm {vid}")
    assert fetched == [REPO]


def test_a_repeated_refusal_leaves_one_job_not_a_chain(held, monkeypatch, capsys):
    conn, vid, fetched = held
    refetch.confirm_path().write_text(json.dumps({str(vid): 1.0}), encoding="utf-8")
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: pytest.fail("ran without its weights"))
    assert adopt.queue_confirmation(conn, vid, adopt.Verdict("code", "inc", REPO, False, "")) is not None
    got = workqueue.run_one(workqueue.pending(conn)[0], popen=_in_process(monkeypatch))
    assert got["state"] == workqueue.FAILED and got["rc"] == 1
    assert workqueue.pending(conn) == []
    assert len(workqueue.confirm_jobs(conn, vid, (workqueue.PENDING, workqueue.RUNNING, workqueue.PAUSED, workqueue.FAILED))) == 1
    assert fetched == []
    assert "its weights cannot be fetched again" in capsys.readouterr().err


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/refetch.py:_confirmed:except")
def test_an_unreadable_ledger_grants_no_refetch(held):
    conn, vid, fetched = held
    refetch.confirm_path().write_text("{not json", encoding="utf-8")
    assert "so it is not downloaded again" in _ensure(conn, f"confirm {vid}")
    assert fetched == []


def test_a_confirm_job_of_another_release_still_counts_as_the_live_one(held):
    conn, vid, _ = held
    old = [str(paths.REPO / ".venv/bin/python-old"), "-m", "harness.cli", "adopt", "--confirm", str(vid)]
    workqueue.add(old, conn=conn)
    assert adopt.queue_confirmation(conn, vid, adopt.Verdict("code", "inc", REPO, False, "")) is None
    assert len(workqueue.pending(conn)) == 1


def test_a_paused_confirm_job_is_not_live_so_a_pausing_job_still_queues_its_successor(held):
    conn, vid, _ = held
    first = adopt.queue_confirmation(conn, vid, adopt.Verdict("code", "inc", REPO, False, ""))
    conn.execute("UPDATE jobs SET state = 'paused' WHERE id = ?", (first["id"],))
    conn.commit()
    assert adopt.queue_confirmation(conn, vid, adopt.Verdict("code", "inc", REPO, False, "")) is not None


def test_the_cleanup_cancels_the_paused_duplicates_logged_and_leaves_one_live_job(held, capsys):
    conn, vid, _ = held
    for i in range(5):
        job = workqueue.add([f"/rel{i}/python", "-m", "harness.cli", "adopt", "--confirm", str(vid)], conn=conn)
        conn.execute("UPDATE jobs SET state = 'paused', rc = 75 WHERE id = ?", (job["id"],))
    other = ms.remember_machine(conn, {"fingerprint": "other/rig", "hw_model": "", "os": "", "arch": "", "memory_gb": 0.0,
                                       "accelerator": "", "runtimes": "", "ceiling_gb": 0.0})
    job = workqueue.add(["/rel9/python", "-m", "harness.cli", "adopt", "--confirm", str(vid)], conn=conn)
    conn.execute("UPDATE jobs SET state = 'paused', rc = 75, machine_id = ? WHERE id = ?", (other, job["id"]))
    job = workqueue.add(["/rel9/python", "-m", "harness.cli", "adopt", "--confirm", str(vid + 999)], conn=conn)
    conn.execute("UPDATE jobs SET state = 'paused', rc = 75, machine_id = ? WHERE id = ?", (other, job["id"]))
    conn.commit()
    assert adopt_cmd.cleanup_confirms(conn, apply=False)["verdicts"] == 1
    assert adopt_cmd.cleanup_confirms(conn, apply=False)["cancelled"] == 5
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE state = 'paused'").fetchone()[0] == 7
    got = adopt_cmd.cleanup_confirms(conn, apply=True)
    assert got["cancelled"] == 5 and got["queued"] == 1
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE state = 'paused'").fetchone()[0] == 2
    assert len(workqueue.pending(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE note LIKE 'cancelled by soh jobs cancel%'").fetchone()[0] == 5
    assert "verdict" in capsys.readouterr().out
    assert adopt_cmd.cleanup_confirms(conn, apply=True)["cancelled"] == 0


def test_the_weights_of_a_held_win_stay_while_its_confirmation_is_queued(held):
    conn, vid, _ = held
    assert disk.busy(conn) == []
    adopt.queue_confirmation(conn, vid, adopt.Verdict("code", "inc", REPO, False, ""))
    assert REPO in disk.busy(conn)
