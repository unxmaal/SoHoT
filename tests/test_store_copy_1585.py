"""A dry run of migrate-to-postgres writes nothing, and a migrate is all or nothing (#1585)."""
import json

import pytest

from harness import memory_store as ms, paths, store, store_copy


def _pg_ready():
    if store.backend() != store.POSTGRES:
        pytest.skip("needs a live Postgres: make test-postgres")


def _legacy_job_file():
    """A pre-#418 queue file in the home, which a FRESH migration step imports into jobs."""
    jobs = paths.home() / "queue" / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / "0007.json").write_text(json.dumps({"id": 7, "title": "legacy", "argv": ["true"], "state": "done"}),
                                    encoding="utf-8")


def _sqlite_with_one_proposal(path):
    conn = store_copy.fresh_sqlite(path)
    ms.record(conn, ms.Seen(name="t/a", source="feed", resolved="t/a", url="https://x"))
    conn.commit()
    conn.close()


def _rows_in_target() -> dict:
    conn = store.postgres_connect()
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in store_copy.tables(conn)}
    finally:
        conn.close()


def test_a_copy_target_is_built_from_the_schema_alone_never_from_the_homes_legacy_files(tmp_path):
    _legacy_job_file()
    conn = store_copy.fresh_sqlite(tmp_path / "s.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == str(ms.SCHEMA_VERSION)
    finally:
        conn.close()


@pytest.mark.postgres
def test_a_dry_run_writes_nothing_to_postgres(tmp_path):
    _pg_ready()
    _legacy_job_file()
    db = tmp_path / "discovery.db"
    _sqlite_with_one_proposal(db)
    got = store_copy.to_postgres_report(db, tmp_path / "snap.db", dry_run=True, replace=False)
    assert got["ok"], got
    assert got["rows"]["proposals"] == 1
    assert not any(_rows_in_target().values())
    assert store_copy.tables(store.postgres_connect()) == []


@pytest.mark.postgres
def test_a_migrate_copies_the_sqlite_rows_and_nothing_from_the_home(tmp_path):
    _pg_ready()
    _legacy_job_file()
    db = tmp_path / "discovery.db"
    _sqlite_with_one_proposal(db)
    got = store_copy.to_postgres_report(db, tmp_path / "snap.db", dry_run=False, replace=False)
    assert got["ok"], got
    rows = _rows_in_target()
    assert rows["jobs"] == 0 and rows["proposals"] == 1


@pytest.mark.postgres
def test_a_migrate_that_does_not_verify_leaves_the_target_as_it_was(tmp_path, monkeypatch):
    _pg_ready()
    db = tmp_path / "discovery.db"
    _sqlite_with_one_proposal(db)
    assert store_copy.to_postgres_report(db, tmp_path / "s1.db", dry_run=False, replace=False)["ok"]
    before = _rows_in_target()
    conn = store_copy.fresh_sqlite(tmp_path / "other.db")
    for name in ("t/b", "t/c"):
        ms.record(conn, ms.Seen(name=name, source="feed", resolved=name, url="https://y"))
    conn.commit()
    conn.close()
    real = store_copy.compare
    monkeypatch.setattr(store_copy, "compare", lambda s, d: [{**r, "ok": False} for r in real(s, d)])
    got = store_copy.to_postgres_report(tmp_path / "other.db", tmp_path / "s2.db", dry_run=False, replace=True)
    assert not got["ok"]
    assert _rows_in_target() == before


@pytest.mark.postgres
def test_a_migrate_that_fails_midway_leaves_the_target_as_it_was(tmp_path, monkeypatch):
    _pg_ready()
    db = tmp_path / "discovery.db"
    _sqlite_with_one_proposal(db)
    assert store_copy.to_postgres_report(db, tmp_path / "s1.db", dry_run=False, replace=False)["ok"]
    before = _rows_in_target()
    real = store_copy._rows

    def broken(conn, table, cols):
        if table == "sightings":
            raise RuntimeError("the disk went away")
        return real(conn, table, cols)

    monkeypatch.setattr(store_copy, "_rows", broken)
    with pytest.raises(RuntimeError):
        store_copy.to_postgres_report(db, tmp_path / "s2.db", dry_run=False, replace=True)
    assert _rows_in_target() == before


def test_a_store_named_by_a_relative_path_is_snapshotted(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.chdir(tmp_path)
    _sqlite_with_one_proposal(tmp_path / "rel.db")
    store_copy.snapshot(Path("rel.db"), Path("backups/snap.db"))
    conn = store_copy.open_sqlite(tmp_path / "backups" / "snap.db", read_only=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1
    finally:
        conn.close()
