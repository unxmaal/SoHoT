"""A migration never opens the store it is migrating a second time. #495."""
import pytest

from harness import downloads, memory_store as ms, paths, runs


def _behind(path, version=40):
    conn = ms.connect(path)
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(version),))
    conn.commit()
    conn.close()


def test_a_step_that_asks_the_default_store_gets_the_one_migrating(monkeypatch):
    db = paths.home() / "discovery.db"
    _behind(db)
    seen = {}

    def step(conn):
        seen["outer"] = conn
        with runs.store() as c:
            seen["inner"] = c
        seen["path"] = downloads.path_of("org/x")
        with pytest.raises(ms.MigrationReentered):
            ms.connect(db)
        return {}
    monkeypatch.setattr(ms, "split_result_artifacts", step)
    conn = ms.connect(db)
    try:
        assert seen["inner"] is seen["outer"]
        assert seen["path"] is None
        assert ms.migrating() is None
        assert ms._stored_schema(conn) == ms.SCHEMA_VERSION
    finally:
        conn.close()


def test_the_migrating_connection_is_not_closed_by_a_borrower(monkeypatch):
    db = paths.home() / "discovery.db"
    _behind(db)

    def step(conn):
        with runs.store():
            pass
        conn.execute("SELECT 1").fetchone()
        return {}
    monkeypatch.setattr(ms, "split_result_artifacts", step)
    ms.connect(db).close()


def test_another_store_opens_normally_during_a_migration(tmp_path, monkeypatch):
    db = paths.home() / "discovery.db"
    _behind(db)
    other = tmp_path / "other.db"

    def step(conn):
        ms.connect(other).close()
        return {}
    monkeypatch.setattr(ms, "split_result_artifacts", step)
    ms.connect(db).close()
    assert other.exists()


def test_a_failed_migration_leaves_nothing_marked_migrating(monkeypatch):
    db = paths.home() / "discovery.db"
    _behind(db)

    def step(conn):
        raise RuntimeError("boom")
    monkeypatch.setattr(ms, "split_result_artifacts", step)
    with pytest.raises(RuntimeError, match="boom"):
        ms.connect(db)
    assert ms.migrating() is None
