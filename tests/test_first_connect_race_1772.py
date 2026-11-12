"""#1772: first connects to a store that needs migrating all succeed, however many arrive at once."""
import os
import sqlite3
import threading
import time

import pytest

from harness import memory_store as ms, store
from tests.racing import race


@pytest.mark.sqlite_store
def test_a_connect_waits_out_another_connect_holding_the_write_lock(tmp_path):
    path = tmp_path / "discovery.db"
    other = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    other.execute("CREATE TABLE early(x)")
    other.execute("BEGIN IMMEDIATE")
    # SQLite answers PRAGMA journal_mode = WAL with 'database is locked' at once while this is held.
    commit = threading.Timer(0.3, other.execute, ("COMMIT",))
    commit.start()
    try:
        conn = ms.connect(path)
    finally:
        commit.join()
        other.close()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == str(ms.SCHEMA_VERSION)
    finally:
        conn.close()


def _waiting(admin, pids) -> bool:
    return bool(pids) and admin.execute("SELECT 1 FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                                        "AND pid = ANY(%s)", (pids,)).fetchone() is not None


@pytest.mark.postgres
def test_a_second_first_connect_waits_for_the_first_ones_ddl_on_postgres(monkeypatch):
    if os.environ.get(store.BACKEND_ENV) != store.POSTGRES:
        pytest.skip("set LOCALHARNESS_STORE=postgres and point PG* at a database")
    import psycopg
    ddl_run, release, first_pid, pids = threading.Event(), threading.Event(), [], []
    real, opened = store.PostgresConnection.executescript, store.postgres_connect

    def held(self, ddl):
        if not first_pid:
            # The first connect's DDL runs and stays uncommitted until the second connect is waiting.
            first_pid.append(self._conn.info.backend_pid)
            self._conn.cursor().execute(store.postgres_ddl(ddl) + store.COMPAT)
            ddl_run.set()
            release.wait(30)
            self._conn.commit()
            return None
        return real(self, ddl)
    monkeypatch.setattr(store.PostgresConnection, "executescript", held)

    def opening(*args, **kwargs):
        conn = opened(*args, **kwargs)
        pids.append(conn._conn.info.backend_pid)
        return conn
    monkeypatch.setattr(store, "postgres_connect", opening)
    errors = []

    def connect():
        try:
            ms.connect().close()
        except Exception as exc:
            errors.append(exc)
    first = threading.Thread(target=connect)
    first.start()
    assert ddl_run.wait(30)
    second = threading.Thread(target=connect)
    second.start()
    try:
        with psycopg.connect(store.dsn(), autocommit=True) as admin:
            deadline = time.monotonic() + 30
            while not _waiting(admin, pids[1:]) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert _waiting(admin, pids[1:])
    finally:
        release.set()
        first.join(60)
        second.join(60)
    assert errors == []


def test_a_racer_that_dies_before_the_start_fails_the_race_with_its_error_instead_of_hanging():
    class Refused(Exception):
        pass

    aborted = []

    class Gate(threading.Barrier):
        def abort(self):
            aborted.append(1)
            super().abort()

    def dies(start):
        raise Refused("connect failed")
    with pytest.raises(Refused, match="connect failed"):
        race([lambda start: start()] * 5 + [dies], timeout=2, barrier=Gate)
    assert aborted == [1]
