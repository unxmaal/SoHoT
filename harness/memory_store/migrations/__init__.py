"""The migration chain: one module vNN.py per schema version, run in order. #484.

A step module sets VERSION and defines any of the PHASES. The runner runs each
phase across every step in VERSION order before the next phase starts, so a
later schema's backfill can still run before an older schema's data step.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import sqlite3
from pathlib import Path
from threading import local as _thread_local

from harness import store
from harness.memory_store.schema import SCHEMA_VERSION

#: columns and indexes run on every migration; early and data only when the store is older.
PHASES = ("columns", "early", "data", "indexes")
_ALWAYS = ("columns", "indexes")


class MigrationReentered(RuntimeError):
    """A migration step tried to open the store it is migrating. #495."""


#: The store a migration in this thread is running on: (its file, its connection). #495.
_MIGRATING = _thread_local()


def migrating():
    """The connection a migration in this thread is running on, or None."""
    return getattr(_MIGRATING, "conn", None)


def _store_file(conn) -> str:
    """The migrated store's file; '' for postgres, which is one store."""
    if store.backend() == store.POSTGRES:
        return ""
    row = conn.execute("PRAGMA database_list").fetchone()
    return str(Path(row[2]).resolve()) if row and row[2] else ":memory:"


def _refuse_reentry(path) -> None:
    if migrating() is None:
        return
    target = "" if path is None else str(Path(path).resolve())
    if target == _MIGRATING.file:
        raise MigrationReentered(
            f"{target or 'the postgres store'} is mid-migration on this thread; "
            f"a step reads it through ms.migrating(), never a second connection")


def steps() -> list:
    """Every vNN step module in this package, in VERSION order."""
    found = [importlib.import_module(f"{__name__}.{m.name}")
             for m in pkgutil.iter_modules(__path__) if re.fullmatch(r"v\d+", m.name)]
    return sorted(found, key=lambda s: s.VERSION)


def due(step, phase: str, have: int) -> bool:
    """Whether `step` runs `phase` on a store at schema `have`."""
    if not hasattr(step, phase):
        return False
    if phase in _ALWAYS:
        return True
    return have < step.VERSION and (have > 0 or getattr(step, "FRESH", False))


def _migrate(conn: sqlite3.Connection) -> None:
    prior = (getattr(_MIGRATING, "conn", None), getattr(_MIGRATING, "file", None))
    _MIGRATING.conn, _MIGRATING.file = conn, _store_file(conn)
    try:
        _migrate_steps(conn)
    finally:
        _MIGRATING.conn, _MIGRATING.file = prior


def _migrate_steps(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    have = int(row["value"]) if row else 0
    if have == SCHEMA_VERSION:
        return
    if have > SCHEMA_VERSION:
        raise RuntimeError(
            f"discovery.db is schema {have}, this code speaks {SCHEMA_VERSION}. "
            f"Refusing to touch a newer store.")
    chain = steps()
    for phase in PHASES:
        for step in chain:
            if due(step, phase, have):
                getattr(step, phase)(conn)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)",
                 (str(SCHEMA_VERSION),))
    conn.commit()
