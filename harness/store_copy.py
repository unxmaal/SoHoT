"""Copy the store between SQLite and Postgres and prove the copy equal: per-table row counts and digests. #1507."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from harness import store

#: Rows written per batch into SQLite and fetched per round trip from Postgres.
BATCH_ROWS = 2000


def tables(conn) -> list[str]:
    """The store's tables, sorted; SQLite's own bookkeeping tables left out."""
    if store.dialect(conn) == store.POSTGRES:
        rows = conn.execute("SELECT table_name AS name FROM information_schema.tables "
                            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'")
    else:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                            "AND name NOT LIKE 'sqlite_%'")
    return sorted(r["name"] for r in rows)


def columns(conn, table: str) -> list[str]:
    """A table's columns, in name order so both backends list them alike."""
    from harness.memory_store.schema import _columns
    return sorted(_columns(conn, table))


def _canonical(v):
    if isinstance(v, bool):
        return ["i", int(v)]
    if isinstance(v, float) and v.is_integer():
        return ["i", int(v)]
    if isinstance(v, int):
        return ["i", v]
    if isinstance(v, float):
        return ["f", repr(v)]
    if isinstance(v, (bytes, bytearray, memoryview)):
        return ["b", bytes(v).hex()]
    return ["s", v] if v is not None else ["n"]


def row_hash(values) -> bytes:
    """One row's hash, the same for a value whichever backend returned it."""
    return hashlib.sha256(json.dumps([_canonical(v) for v in values],
                                     ensure_ascii=False).encode()).digest()


def _rows(conn, table: str, cols: list[str]):
    """Every row of `table` as tuples over `cols`, streamed."""
    sql = f"SELECT {', '.join(cols)} FROM {table}"
    if store.dialect(conn) == store.POSTGRES:
        from psycopg.rows import tuple_row
        with conn._conn.cursor(name=f"copy_{table}", row_factory=tuple_row) as cur:
            cur.itersize = BATCH_ROWS
            cur.execute(sql)
            yield from cur
        return
    cur = conn.execute(sql)
    while batch := cur.fetchmany(BATCH_ROWS):
        yield from (tuple(r) for r in batch)


def digest(conn, table: str, cols: list[str]) -> tuple[int, str]:
    """(rows, digest) of a table over `cols`: order-free, so neither backend's sort order matters."""
    hashes = sorted(row_hash(r) for r in _rows(conn, table, cols))
    h = hashlib.sha256()
    for x in hashes:
        h.update(x)
    return len(hashes), h.hexdigest()


def compare(src, dst) -> list[dict]:
    """Per table of `src`: its rows and digest on both sides, over the columns `src` holds."""
    out, there = [], set(tables(dst))
    for t in tables(src):
        cols = columns(src, t)
        n, d = digest(src, t, cols)
        if t not in there:
            out.append({"table": t, "rows": n, "digest": d, "dst_rows": None, "dst_digest": None, "ok": False,
                        "why": "missing in the destination"})
            continue
        missing = [c for c in cols if c not in set(columns(dst, t))]
        if missing:
            out.append({"table": t, "rows": n, "digest": d, "dst_rows": None, "dst_digest": None, "ok": False,
                        "why": f"columns missing in the destination: {', '.join(missing)}"})
            continue
        dn, dd = digest(dst, t, cols)
        out.append({"table": t, "rows": n, "digest": d, "dst_rows": dn, "dst_digest": dd,
                    "ok": n == dn and d == dd, "why": "" if (n, d) == (dn, dd) else "differs"})
    return out


def gaps(src, dst) -> list[str]:
    """What the destination's schema cannot hold of the source: tables or columns it lacks."""
    out, there = [], set(tables(dst))
    for t in tables(src):
        if t not in there:
            out.append(f"table {t}: not in the destination's schema")
            continue
        lack = sorted(set(columns(src, t)) - set(columns(dst, t)))
        if lack:
            out.append(f"table {t}: columns {', '.join(lack)} not in the destination's schema")
    return out


def _schema(conn) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
    return int(row["value"]) if row else 0


def _sequences(conn) -> dict:
    """SQLite's AUTOINCREMENT high-water marks, which a cancelled top id must never fall below."""
    try:
        return {r["name"]: int(r["seq"]) for r in conn.execute("SELECT name, seq FROM sqlite_sequence")}
    except sqlite3.Error:
        return {}


def to_postgres(src, dst) -> list[str]:
    """Replace every table of Postgres `dst` with `src`'s rows; identities resume above the old high-water."""
    raw = dst._conn
    names = tables(src)
    with raw.cursor() as cur:
        cur.execute("SET LOCAL session_replication_role = replica")
        cur.execute("TRUNCATE " + ", ".join(tables(dst)) + " RESTART IDENTITY CASCADE")
        for t in names:
            cols = columns(src, t)
            with cur.copy(f"COPY {t} ({', '.join(cols)}) FROM STDIN") as cp:
                for row in _rows(src, t, cols):
                    cp.write_row(row)
        high = _sequences(src)
        cur.execute("SELECT table_name FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND column_name = 'id' AND is_identity = 'YES'")
        for (t,) in cur.fetchall():
            cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {t}")
            top = max(cur.fetchone()[0], high.get(t, 0))
            if top:
                cur.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true)", (t, top))
    raw.commit()
    return names


def to_sqlite(src, dst) -> list[str]:
    """Replace every table of SQLite `dst` with Postgres `src`'s rows."""
    names = tables(src)
    dst.execute("PRAGMA foreign_keys = OFF")
    for t in tables(dst):
        dst.execute(f"DELETE FROM {t}")
    for t in names:
        cols = columns(src, t)
        sql = f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        batch = []
        for row in _rows(src, t, cols):
            batch.append(tuple(row))
            if len(batch) >= BATCH_ROWS:
                dst.executemany(sql, batch)
                batch = []
        if batch:
            dst.executemany(sql, batch)
    dst.commit()
    dst.execute("PRAGMA foreign_keys = ON")
    return names


def snapshot(db: Path, dest: Path) -> Path:
    """A consistent .backup of the SQLite store, read through a read-only connection."""
    from harness import migration_check
    dest.parent.mkdir(parents=True, exist_ok=True)
    migration_check._copy_store(Path(db), Path(dest))
    return dest


def open_sqlite(path: Path, *, read_only: bool):
    if read_only:
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def fresh_postgres(environ=None):
    """The Postgres store opened and brought to this code's schema, whatever LOCALHARNESS_STORE says."""
    from harness import memory_store as ms
    conn = store.postgres_connect(environ)
    conn.executescript(ms._DDL)
    ms._migrate(conn)
    return conn


def fresh_sqlite(path: Path):
    """A new SQLite store at `path` at this code's schema."""
    from harness import memory_store as ms
    conn = open_sqlite(path, read_only=False)
    conn.executescript(ms._DDL)
    ms._migrate(conn)
    return conn


def _occupied(conn) -> list[str]:
    return [t for t in tables(conn) if t != "meta"
            and conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()]


def to_postgres_report(db: Path, snap: Path, *, dry_run: bool, replace: bool, environ=None) -> dict:
    """`soh store migrate-to-postgres`: snapshot, copy, verify. The SQLite file is only ever read."""
    from harness.memory_store.schema import SCHEMA_VERSION
    started = time.time()
    snapshot(db, snap)
    src = open_sqlite(snap, read_only=True)
    try:
        have = _schema(src)
        if have != SCHEMA_VERSION:
            return {"ok": False, "snapshot": str(snap),
                    "why": f"the SQLite store is schema {have}, this code speaks {SCHEMA_VERSION}: "
                           f"deploy this code on SQLite first"}
        dst = fresh_postgres(environ)
        try:
            missing = gaps(src, dst)
            busy = _occupied(dst)
            report = {"snapshot": str(snap), "schema": have, "gaps": missing, "occupied": busy,
                      "tables": len(tables(src))}
            if missing:
                return {**report, "ok": False, "why": "the Postgres schema cannot hold every table and column"}
            if busy and not replace:
                return {**report, "ok": False,
                        "why": f"the Postgres store already holds rows in {', '.join(busy)}; --replace overwrites"}
            if dry_run:
                fk = len(src.execute("PRAGMA foreign_key_check").fetchall())
                return {**report, "ok": True, "dry_run": True, "foreign_key_violations": fk,
                        "rows": {t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables(src)}}
            to_postgres(src, dst)
            checked = compare(src, dst)
            return {**report, "ok": all(c["ok"] for c in checked), "verify": checked,
                    "seconds": round(time.time() - started, 1)}
        finally:
            dst.close()
    finally:
        src.close()


def to_sqlite_report(dest: Path, environ=None) -> dict:
    """`soh store export-to-sqlite`: the Postgres store into a NEW SQLite file, verified; nothing else changes."""
    if dest.exists():
        return {"ok": False, "why": f"{dest} exists; name a new file"}
    started = time.time()
    src = store.postgres_connect(environ)
    try:
        src._conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        dst = fresh_sqlite(dest)
        try:
            missing = gaps(src, dst)
            if missing:
                return {"ok": False, "gaps": missing, "why": "the SQLite schema cannot hold every table and column"}
            to_sqlite(src, dst)
            checked = compare(src, dst)
            src.rollback()
            return {"ok": all(c["ok"] for c in checked), "dest": str(dest), "verify": checked,
                    "seconds": round(time.time() - started, 1)}
        finally:
            dst.close()
    finally:
        src.close()
