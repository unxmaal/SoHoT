"""Queue items run under leases: taken by class, beaten, lapsed; a gone worker's jobs are retaken; delegations are rows. #1558."""
import os
import subprocess
import sys
import threading
import time
import types

import pytest

from harness import item_lease, resources, serve_lease
from harness import memory_store as ms
from harness import workqueue as wq


def _conn():
    return ms.connect()


def test_a_running_job_holds_a_lease_on_its_class_until_it_ends():
    seen = {}

    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        c = _conn()
        seen["live"] = item_lease.live(c)
        c.close()
        return types.SimpleNamespace(returncode=0)

    job = wq.add([sys.executable, "-c", "pass"], title="plain")
    assert wq.run_pending(popen=popen)[0]["state"] == wq.DONE
    [lease] = seen["live"]
    assert (lease["resource"], lease["item"], lease["job_id"]) == (resources.GPU, f"job {job['id']}", int(job["id"]))
    assert item_lease.live(_conn()) == [], "the lease is released when the job ends"


def test_a_class_at_capacity_takes_no_second_lease_until_the_first_is_released():
    c = _conn()
    first = item_lease.take(c, resources.GPU, "job 0001")
    assert first is not None and item_lease.take(c, resources.GPU, "job 0002") is None
    assert item_lease.take(c, resources.NETWORK, "job 0003") is not None, "another class is not held by the gpu"
    item_lease.release(c, first["id"])
    assert item_lease.take(c, resources.GPU, "job 0002") is not None


def test_two_takers_racing_for_the_last_place_never_both_win():
    got, start, opening = [], threading.Barrier(6), threading.Lock()
    _conn().close()

    def taker(n):
        with opening:  # a fresh store's first connects race on journal_mode; the race under test is the take
            c = _conn()
        start.wait()
        got.append(item_lease.take(c, resources.GPU, f"job {n:04d}"))
        c.close()

    threads = [threading.Thread(target=taker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sum(1 for g in got if g) == 1 and len(got) == 6
    assert len(item_lease.live(_conn(), resources.GPU)) == 1


def test_a_lease_nobody_beats_lapses_and_frees_its_place():
    c = _conn()
    now = time.time()
    lease = item_lease.take(c, resources.GPU, "job 0001", ttl_s=10, now=now)
    assert item_lease.live(c, now=now + 5) and not item_lease.live(c, now=now + 11)
    assert not item_lease.beat(c, lease["id"], now=now + 11), "a lapsed lease is not revived by a late beat"
    assert item_lease.take(c, resources.GPU, "job 0002", now=now + 11) is not None


def test_a_job_whose_class_is_leased_elsewhere_goes_back_to_pending():
    c = _conn()
    item_lease.take(c, resources.GPU, "a gpu item outside this worker")
    job = wq.add([sys.executable, "-c", "pass"], title="plain")
    assert wq.run_one(wq.get(job["id"]), popen=lambda *a, **k: pytest.fail("ran without a lease")) is None
    got = wq.get(job["id"])
    assert got["state"] == wq.PENDING and "leased to capacity" in got["note"]


def _running(job, pid=None):
    """Mark a job running on this machine as a worker that then died would have left it."""
    c = _conn()
    c.execute("UPDATE jobs SET state = ?, started_at = ?, machine_id = ? WHERE id = ?",
              (wq.RUNNING, time.time() - 60, ms.remember_machine(c), int(job["id"])))
    c.commit()
    if pid is not None:
        wq._pid_file(job["id"]).write_text(str(pid), encoding="utf-8")


def test_a_gone_workers_eval_that_stored_a_run_waits_again_to_resume_it(tmp_path, monkeypatch):
    from harness import runs
    argv = ["uv", "run", "python", "-m", "evals.run", "--modality", "pii", "--candidates", "pii-regex"]
    job = wq.add(argv, title="eval")
    other = wq.add(["soh-batch-job"], title="batch")
    _running(job)
    _running(other)
    monkeypatch.setattr(runs, "for_job", lambda c, i: {"path": str(tmp_path / "x")} if i == int(job["id"]) else None)
    assert wq._recover() == []
    got = wq.get(job["id"])
    assert got["state"] == wq.PENDING and got["argv"] == [*argv, "--out", str(tmp_path / "x"), "--resume"]
    assert wq.get(other["id"])["state"] == wq.FAILED and "interrupted" in wq.get(other["id"])["note"]


def test_a_job_a_gone_worker_left_running_is_watched_under_a_lease_not_failed():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    job = wq.add(["soh-batch-job"], title="batch")
    _running(job, child.pid)
    try:
        left = wq._recover()
        assert [j["id"] for j in left] == [job["id"]] and wq.get(job["id"])["state"] == wq.RUNNING
        t = threading.Thread(target=wq._watch_left, args=(left[0], 0.05))
        t.start()
        # The watcher's first store open can take seconds on a Windows runner: wait for its lease, never a fixed time.
        for _ in range(200):
            if item_lease.live(_conn()):
                break
            time.sleep(0.05)
        assert [x["job_id"] for x in item_lease.live(_conn())] == [int(job["id"])], "the live job keeps the gpu"
        child.kill()
        child.wait(10)
        t.join(10)
    finally:
        child.kill()
    assert wq.get(job["id"])["state"] == wq.FAILED and item_lease.live(_conn()) == []


def test_a_delegations_serving_lease_is_a_row_beside_the_jobs():
    lease = serve_lease.Lease("decide", "a decide delegation")
    [row] = item_lease.live(_conn(), item_lease.SERVING)
    assert (row["item"], row["state"], row["pid"]) == ("delegation decide", serve_lease.WAITING, os.getpid())
    lease.serving()
    assert serve_lease.holders()[0]["state"] == serve_lease.SERVING
    lease.drop()
    assert serve_lease.holders() == [] and item_lease.live(_conn(), item_lease.SERVING) == []


def test_a_dead_delegations_lease_is_released_when_read():
    lease = serve_lease.Lease("decide", "a decide delegation")
    c = _conn()
    c.execute("UPDATE leases SET pid = ? WHERE id = ?", (2 ** 22 + 12345, lease.id))
    c.commit()
    assert serve_lease.holders() == [] and item_lease.live(c, item_lease.SERVING) == []


def test_serving_goes_on_unleased_when_the_store_will_not_answer(monkeypatch, capsys):
    def down():
        raise OSError("store down")
    monkeypatch.setattr(ms, "connect", down)
    lease = serve_lease.Lease("decide", "a decide delegation")
    lease.serving()
    lease.idle()
    lease.drop()
    assert lease.id is None and serve_lease.holders() == []
    assert "store did not answer" in capsys.readouterr().err


def test_soh_jobs_list_shows_each_live_lease(capsys):
    from harness import cli
    item_lease.take(_conn(), resources.GPU, "job 0042")
    serve_lease.Lease("decide", "a decide delegation")
    capsys.readouterr()
    assert cli.main(["jobs", "list"]) == 0
    out = capsys.readouterr().out
    assert "gpu leased by job 0042" in out and "serving leased by delegation decide (waiting)" in out
