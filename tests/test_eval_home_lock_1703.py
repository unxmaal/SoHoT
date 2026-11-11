"""An eval in a scratch home answers "is the machine held" from the machine's own gpu lease and generation.lock. #1703."""
import os
import sqlite3

import pytest

from harness import delegate, exclusive, item_lease, paths, resources, store
from harness import memory_store as ms
from harness import workqueue as wq


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    monkeypatch.delenv(paths.EVAL_ENV, raising=False)


def _scratch(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR)
    return paths.eval_home(tmp_path / "scratch")


def _leases_in(home):
    with paths.seated(home), store.pinned(store.SQLITE):
        conn = ms.connect()
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM leases")]
        finally:
            conn.close()


def test_a_scratch_eval_s_delegation_sees_the_machine_s_gpu_lease_and_writes_no_lease_row(tmp_path, monkeypatch):
    live = paths.home()
    conn = ms.connect()
    item_lease.take(conn, resources.GPU, f"image pid {os.getpid()}", state="image", detail="image")
    conn.close()
    outside = exclusive.gpu_holder()
    assert outside["kind"] == "image" and "image" in delegate.held_now()
    scratch = _scratch(tmp_path, monkeypatch)
    assert (paths.home(), paths.machine_home()) == (scratch, live)
    assert exclusive.gpu_holder() == outside, "answered as it is outside the eval home"
    assert "image" in delegate.held_now() and exclusive.gpu_leases() == 1
    with exclusive._machine() as machine:
        assert [h["state"] for h in item_lease.live(machine, resources.GPU)] == ["image"]
    assert _leases_in(scratch) == [], "the scratch store gets no lease row"


def test_a_scratch_eval_sees_another_project_s_lockf_and_its_own_hold_takes_the_machine_s_flock(tmp_path, monkeypatch):
    ms.connect().close()
    live_lock = exclusive.lock_path()
    fd = os.open(live_lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        assert exclusive._take(fd), "lockf -k generation.lock, as infovore takes it (DECISION #210)"
        _scratch(tmp_path, monkeypatch)
        assert "lockf" in delegate.held_now() and exclusive.gpu_leases() == 1
        with exclusive.try_held("eval") as got:
            assert got is False, "a scratch eval waits on the machine's generation.lock, not its own"
    finally:
        exclusive._release(fd)
        os.close(fd)
    assert delegate.held_now() == ""
    with exclusive.try_held("eval") as got:
        assert got is True
        assert exclusive._taken(live_lock), "a lockf user on the machine waits for the scratch eval"


@pytest.mark.sqlite_store
def test_a_scratch_eval_whose_machine_store_will_not_open_is_refused(tmp_path, monkeypatch):
    (paths.home() / "discovery.db").mkdir()
    _scratch(tmp_path, monkeypatch)
    with pytest.raises(delegate.Refused, match="unreachable"):
        delegate.held_now()


@pytest.mark.sqlite_store
def test_a_scratch_eval_whose_machine_store_has_no_lease_ledger_is_refused(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    sqlite3.connect(other / "discovery.db").execute("CREATE TABLE t (a)").connection.close()
    monkeypatch.setenv(paths.MACHINE_ENV, str(other))
    _scratch(tmp_path, monkeypatch)
    with pytest.raises(delegate.Refused, match="cannot be read"):
        delegate.held_now()


@pytest.mark.sqlite_store
def test_a_machine_home_with_no_store_and_no_lock_is_free_and_left_untouched(tmp_path, monkeypatch):
    bare = tmp_path / "bare"
    (bare / "queue").mkdir(parents=True)
    monkeypatch.setenv(paths.MACHINE_ENV, str(bare))
    _scratch(tmp_path, monkeypatch)
    assert delegate.held_now() == "" and exclusive.gpu_leases() == 0
    assert [p.name for p in bare.rglob("*")] == ["queue"], "a check creates no lock file or store there"


def test_eval_home_records_the_machine_home_it_leaves_for_that_scratch_home_only(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.MACHINE_ENV)
    monkeypatch.delenv(paths.MACHINE_STORE_ENV, raising=False)
    monkeypatch.delenv(paths.ENV_VAR)
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    scratch = paths.eval_home(tmp_path / "scratch")
    assert os.environ[paths.MACHINE_ENV] == str(paths.DEFAULT_HOME)
    assert (os.environ[paths.MACHINE_STORE_ENV], os.environ[store.BACKEND_ENV]) == (store.POSTGRES, store.SQLITE)
    assert paths.machine_home() == paths.DEFAULT_HOME.resolve() != scratch
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "child"))
    assert paths.machine_home() == (tmp_path / "child").resolve(), "a child given its own home keeps its own lock"
