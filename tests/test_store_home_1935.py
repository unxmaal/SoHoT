"""Two homes on one machine share one store: only the home that works it recovers, claims or settles its jobs. #1935"""
import os
import sys
from pathlib import Path

import pytest

from harness import deploy, job_procs, paths, store, store_home
from harness import memory_store as ms
from harness import workqueue as wq


@pytest.fixture(autouse=True)
def _no_marker(monkeypatch):
    from harness import exclusive
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)


def _claim_here() -> str:
    conn = ms.connect()
    try:
        return store_home.refused(conn)
    finally:
        conn.close()


def _running(kind: str = "command") -> dict:
    job = wq.add([sys.executable, "-c", "pass"], kind=kind)
    conn = ms.connect()
    try:
        conn.execute("UPDATE jobs SET state = ?, machine_id = ? WHERE id = ?",
                     (wq.RUNNING, ms.remember_machine(conn), int(job["id"])))
        conn.commit()
    finally:
        conn.close()
    job_procs._pid_file(job["id"]).write_text(str(os.getpid()), encoding="utf-8")
    return job


def _home_b(tmp_path, monkeypatch) -> Path:
    """A second home on this machine whose store is the first home's."""
    a = paths.home()
    b = tmp_path / "home-b"
    b.mkdir()
    if store.backend() == store.SQLITE:
        (b / "discovery.db").symlink_to(a / "discovery.db")
    monkeypatch.setenv(paths.ENV_VAR, str(b))
    monkeypatch.setenv(paths.MACHINE_ENV, str(b))
    return b


def test_the_first_home_to_ask_holds_the_claim_and_keeps_it():
    assert _claim_here() == ""
    assert _claim_here() == ""
    conn = ms.connect()
    try:
        assert store_home.claimed(conn, ms.machine_row(conn)) == str(paths.home().resolve())
    finally:
        conn.close()


def test_a_second_homes_worker_neither_recovers_nor_claims_the_first_homes_jobs(tmp_path, monkeypatch, capsys):
    a = paths.home()
    running = _running()
    waiting = wq.add([sys.executable, "-c", "pass"])
    assert _claim_here() == ""
    _home_b(tmp_path, monkeypatch)
    assert wq.run_pending() == []
    assert wq.get(running["id"])["state"] == wq.RUNNING
    assert wq.get(waiting["id"])["state"] == wq.PENDING
    said = capsys.readouterr().out
    assert f"refused: {a.resolve()} works this store" in said


def test_a_second_homes_deploy_settle_leaves_the_first_homes_deploy_job_running(tmp_path, monkeypatch):
    job = _running(kind=deploy.KIND)
    assert _claim_here() == ""
    _home_b(tmp_path, monkeypatch)
    deploy.settle(alive=lambda pid: False, spawn=lambda *a, **k: None)
    assert wq.get(job["id"])["state"] == wq.RUNNING


def test_the_working_homes_deploy_settle_still_closes_a_dead_deploy_job():
    job = _running(kind=deploy.KIND)
    job_procs._pid_file(job["id"]).unlink()
    deploy.settle(alive=lambda pid: False, spawn=lambda *a, **k: None)
    assert wq.get(job["id"])["state"] == wq.FAILED


def test_the_working_home_recovers_its_own_dead_job():
    job = _running()
    job_procs._pid_file(job["id"]).unlink()
    wq.run_pending()
    assert wq.get(job["id"])["state"] == wq.FAILED


def test_the_live_home_takes_the_claim_from_another_home(tmp_path, monkeypatch):
    assert _claim_here() == ""
    b = _home_b(tmp_path, monkeypatch)
    assert _claim_here().startswith("refused: ")
    from harness import monitor
    monkeypatch.setattr(monitor, "live_home", lambda home=None: Path(home) == b.resolve())
    assert _claim_here() == ""


def test_a_claim_whose_home_is_gone_passes_to_the_home_that_asks(tmp_path, monkeypatch):
    first = tmp_path / "home-gone"
    first.mkdir()
    conn = ms.connect()
    try:
        assert store_home.refused(conn, home=first) == ""
        assert store_home.refused(conn).startswith("refused: ")
        first.rmdir()
        assert store_home.refused(conn) == ""
        assert store_home.claimed(conn, ms.machine_row(conn)) == str(paths.home().resolve())
    finally:
        conn.close()


def test_each_machine_has_its_own_claim():
    conn = ms.connect()
    try:
        assert store_home.refused(conn) == ""
        mid = ms.machine_row(conn)
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (f"{store_home.KEY}{mid + 1}", "/elsewhere"))
        assert store_home.refused(conn) == ""
        assert store_home.claimed(conn, mid + 1) == "/elsewhere"
    finally:
        conn.close()
