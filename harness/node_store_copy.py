"""Copy a node's SQLite store before an install and put it back for a rollback, with the standard library only. #2023."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

#: The one copy a node keeps: the store as the release before the pending install left it.
NAME = "node-install.db"


def _postgres(home: Path, environ) -> bool:
    got = str(environ.get("LOCALHARNESS_STORE") or "").strip()
    if not got:
        try:
            got = str(json.loads((home / "store.json").read_text(encoding="utf-8")).get("backend") or "")
        except (OSError, ValueError, AttributeError):
            got = ""
    return got.strip().lower() == "postgres"


def _schema(conn) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    return int(row[0]) if row else 0


def _copy(src: Path, dest: Path) -> int:
    """SQLite's backup API from a mode=ro connection of SRC onto DEST; the schema DEST then holds."""
    s = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)
    try:
        d = sqlite3.connect(str(dest), timeout=60)
        try:
            s.backup(d)
            return _schema(d)
        finally:
            d.close()
    finally:
        s.close()


def backup(home, environ=None) -> list[str]:
    """Copy HOME's store to backups/NAME; the lines saying where and at which schema, or `backup none: why`."""
    home = Path(home)
    db = home / "discovery.db"
    if _postgres(home, os.environ if environ is None else environ):
        return [f"backup none: the store of {home} is Postgres, which a node install does not copy"]
    if not db.is_file():
        return [f"backup none: no store at {db}"]
    dest = home / "backups" / NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Written in place: a copy that fails part way fails the install, and its path is never recorded.
    return [f"backup {dest}", f"backup_schema {_copy(db, dest)}"]


def restore(home, src) -> list[str]:
    """Put the copy SRC back over HOME's store; the lines naming it and the schema the store is now at."""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"no store copy at {src}")
    return [f"restored {src}", f"restored_schema {_copy(src, Path(home) / 'discovery.db')}"]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 2 and args[0] == "backup":
            lines = backup(args[1])
        elif len(args) == 3 and args[0] == "restore":
            lines = restore(args[1], args[2])
        else:
            print("usage: node_store_copy.py backup HOME | restore HOME COPY", file=sys.stderr)
            return 2
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"node store copy {args[0]} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
