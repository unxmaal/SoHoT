"""Opening the store: the path, the pragmas, the live-store guard (#455), then the migration chain."""
from __future__ import annotations

from pathlib import Path
import os
import sqlite3

from harness import memory_store as ms, paths, store
from harness.memory_store.migrations import _refuse_reentry
from harness.memory_store.schema import SCHEMA_VERSION, _DDL


#: How long a writer waits for the lock before giving up. Generous because the
#: alternative is a failed sweep, and a discovery write is milliseconds: this
#: is a queue depth, not a latency budget.
BUSY_TIMEOUT_SECONDS = 30.0


def db_path() -> Path:
    return paths.home() / "discovery.db"


def connect(path: Path | None = None):
    """Open (creating if needed) and migrate to SCHEMA_VERSION.

    SQLite unless LOCALHARNESS_STORE says postgres, because `lh` on a laptop
    must keep working with no cluster at all -- a discovery engine that only
    runs in Kubernetes is a worse tool than the one that already exists.
    """
    if store.backend() == store.POSTGRES:
        _refuse_reentry(None)
        conn = store.postgres_connect()
        conn.executescript(_DDL)
        ms._migrate(conn)
        return conn
    path = Path(path) if path is not None else db_path()
    _refuse_reentry(path)
    if not path.exists():
        _guard_live(path, lambda: 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    try:
        _guard_live(path, lambda: _stored_schema(conn))
    except Exception:
        conn.close()
        raise
    conn.execute("PRAGMA foreign_keys = ON")
    # SQLite does not corrupt under concurrent writers -- it SERIALISES them,
    # and an unprepared second writer gets `database is locked` at once. These
    # two lines are the difference between "waits its turn" and "fails", and
    # the discovery store is about to have several writers (#148).
    #
    # WAL also lets readers proceed during a write, which matters because the
    # sweep reads while the judge writes. The caveat is the filesystem: WAL
    # needs real shared memory and is unsafe over NFS-style mounts, so a
    # network-mounted store wants a single writer rather than this.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")
    conn.executescript(_DDL)
    ms._migrate(conn)
    return conn


class LiveStoreRefused(RuntimeError):
    """The live store is behind this code and this code is not the deploy. #455."""


def _stored_schema(conn) -> int:
    if not conn.execute("SELECT 1 FROM sqlite_master "
                        "WHERE type='table' AND name='meta'").fetchone():
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    return int(row["value"]) if row else 0


def _guard_live(path: Path, schema) -> None:
    """Only the deploy checkout moves the live store's schema; else services refuse it."""
    if not paths.is_live(path) or os.environ.get(paths.ALLOW_MIGRATE_ENV) == "1":
        return
    have = schema()
    if have >= SCHEMA_VERSION:
        return
    deploy = paths.runs_elsewhere()
    if deploy is None:
        return
    raise LiveStoreRefused(
        f"{path} is the live store at schema {have}; this checkout "
        f"({paths.REPO}) speaks {SCHEMA_VERSION} and is not the deploy checkout "
        f"({deploy}). Migrating it would leave the deployed "
        f"services refusing a newer store. Merge to main and run "
        f"./scripts/launchd.sh install to deploy, or for a scratch run set "
        f"{paths.ENV_VAR}=<scratch dir>. {paths.ALLOW_MIGRATE_ENV}=1 overrides.")
