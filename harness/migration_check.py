"""What a migrated store must hold, and a dry run of a real store's migration. #478."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from harness import memory_store as ms
from harness import paths

INVARIANTS = ("integrity", "foreign_keys", "schema", "proposal_state",
              "verdict_reason", "adoptions_resolve", "machines_unique",
              "downloads_sane", "results_split")

#: Shown in a failing check's detail; the rest are counted.
SHOWN = 5


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def schema(conn) -> int:
    return ms._stored_schema(conn)


def _tables(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def counts(conn) -> dict[str, int]:
    """Rows per table, meta aside."""
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in _tables(conn) if t != "meta"}


def _integrity(conn) -> list[str]:
    got = [r[0] for r in conn.execute("PRAGMA integrity_check")]
    return [] if got == ["ok"] else got


def _say(bad: list) -> str:
    more = f" (+{len(bad) - SHOWN} more)" if len(bad) > SHOWN else ""
    return f"{len(bad)}: " + "; ".join(str(b) for b in bad[:SHOWN]) + more


def _check(name: str, bad: list) -> Check:
    return Check(name, not bad, _say(bad) if bad else "")


def _proposal_state(conn) -> list:
    bad = []
    for r in conn.execute(
            "SELECT p.name, p.state, p.state_verdict_id AS vid, v.proposal_id AS "
            "vp, v.outcome, p.id, (SELECT COUNT(*) FROM verdicts w WHERE "
            "w.proposal_id = p.id) AS n FROM proposals p LEFT JOIN verdicts v "
            "ON v.id = p.state_verdict_id"):
        if r["state"] not in ("", *ms.VERDICTS):
            bad.append(f"{r['name']}: state {r['state']!r} is not an outcome")
        elif not r["state"]:
            if r["n"] or r["vid"] is not None:
                bad.append(f"{r['name']}: {r['n']} verdict(s) and no state")
        elif r["vp"] != r["id"] or r["outcome"] != r["state"]:
            bad.append(f"{r['name']}: state {r['state']} not held by its "
                       f"verdict {r['vid']} ({r['outcome']})")
    return bad


def _verdict_reason(conn) -> list:
    from harness import reasons
    return [f"verdict {r['id']} ({r['tier']} {r['outcome']}): "
            f"reason {r['reason']!r}" for r in conn.execute(
                "SELECT id, tier, outcome, reason FROM verdicts ORDER BY id")
            if r["reason"] not in reasons.REASONS]


def _adoptions(conn) -> list:
    from harness import adopt
    bad = []
    for r in conn.execute(
            "SELECT a.*, c.id AS c, i.id AS i, v.id AS v, x.id AS x "
            "FROM adoptions a LEFT JOIN candidates c ON c.id = a.candidate_id "
            "LEFT JOIN candidates i ON i.id = a.incumbent_id "
            "LEFT JOIN verdicts v ON v.id = a.verdict_id "
            "LEFT JOIN runs x ON x.id = a.run_id ORDER BY a.id"):
        why = [w for w, broken in (
            ("no candidate", r["c"] is None),
            ("no incumbent", r["incumbent_id"] is not None and r["i"] is None),
            ("no verdict", r["verdict_id"] is not None and r["v"] is None),
            ("no run", r["run_id"] is not None and r["x"] is None),
            ("no lane", not r["lane"]),
            (f"how {r['how']!r}", r["how"] not in adopt.HOW)) if broken]
        if why:
            bad.append(f"adoption {r['id']}: {', '.join(why)}")
    return bad


def _machines(conn) -> list:
    from harness import machine
    seen: dict[str, int] = {}
    bad = []
    for r in conn.execute("SELECT * FROM machines ORDER BY id"):
        fp = (machine.fingerprint(r["hw_model"], r["os"], r["arch"])
              if (r["hw_model"] or r["os"] or r["arch"]) else r["fingerprint"])
        if fp in seen:
            bad.append(f"machines {seen[fp]} and {r['id']} are one machine {fp}")
        elif fp != r["fingerprint"]:
            bad.append(f"machine {r['id']} is stored as {r['fingerprint']}, is {fp}")
        seen.setdefault(fp, r["id"])
    return bad


def _downloads(conn) -> list:
    from harness import downloads as d
    origins = {d.FETCH, d.LINK, d.SCRIPT, d.SCAN, d.BACKFILL, d.PARTIAL}
    bad = []
    for r in conn.execute("SELECT * FROM downloads ORDER BY id"):
        why = [w for w, broken in (
            (f"kind {r['kind']!r}", r["kind"] not in d.KINDS),
            ("no path", not r["path"]),
            (f"origin {r['origin']!r}", r["origin"] not in origins),
            ("negative size", (r["bytes"] or 0) < 0 or (r["files"] or 0) < 0),
            ("removed by nobody", r["removed_at"] is not None
             and not r["removed_by"]),
            ("removed yet complete", r["removed_at"] is not None
             and r["complete"])) if broken]
        if why:
            bad.append(f"download {r['id']} {r['repo']}: {', '.join(why)}")
    return bad


def _results(conn) -> list:
    cols = ms._columns(conn, "results")
    bad = [f"results lacks {c}" for c in ("output", "artifact_path")
           if c not in cols]
    if "artifact" in cols and sqlite3.sqlite_version_info >= (3, 35, 0):
        bad.append("results still carries the artifact column")
    if "artifact_path" in cols:
        bad += [f"result {r['id']}: artifact_path is text" for r in conn.execute(
            "SELECT id FROM results WHERE artifact_path LIKE '%' || char(10) || '%'")]
    return bad


def invariants(conn) -> list[Check]:
    """Every check over a store; reads only."""
    fk = [f"{r[0]} row {r[1]} -> {r[2]}"
          for r in conn.execute("PRAGMA foreign_key_check")]
    have = schema(conn)
    return [
        _check("integrity", _integrity(conn)),
        _check("foreign_keys", fk),
        _check("schema", [] if have == ms.SCHEMA_VERSION
               else [f"schema {have}, head is {ms.SCHEMA_VERSION}"]),
        _check("proposal_state", _proposal_state(conn)),
        _check("verdict_reason", _verdict_reason(conn)),
        _check("adoptions_resolve", _adoptions(conn)),
        _check("machines_unique", _machines(conn)),
        _check("downloads_sane", _downloads(conn)),
        _check("results_split", _results(conn)),
    ]


def _copy_store(src: Path, dest: Path) -> None:
    """A consistent copy through the backup API, opening `src` read-only."""
    last = None
    for mode in ("mode=ro", "immutable=1"):
        try:
            ro = sqlite3.connect(f"{src.as_uri()}?{mode}", uri=True)
            try:
                out = sqlite3.connect(dest)
                try:
                    ro.backup(out)
                finally:
                    out.close()
            finally:
                ro.close()
            return
        except sqlite3.Error as exc:
            last = exc
            dest.unlink(missing_ok=True)
    raise last


def _copy_home(src_home: Path, home: Path) -> None:
    for rel in ms.LEGACY_FILES:
        f = src_home / rel
        if f.is_file():
            (home / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, home / rel)
    if (src_home / "queue" / "jobs").is_dir():
        shutil.copytree(src_home / "queue" / "jobs", home / "queue" / "jobs")
    # Receipts are read, never written, by the steps that import them.
    if (src_home / "runs").is_dir():
        (home / "runs").symlink_to((src_home / "runs").resolve(),
                                   target_is_directory=True)


@contextmanager
def _home(home: Path):
    was = os.environ.get(paths.ENV_VAR)
    os.environ[paths.ENV_VAR] = str(home)
    try:
        yield
    finally:
        if was is None:
            os.environ.pop(paths.ENV_VAR, None)
        else:
            os.environ[paths.ENV_VAR] = was


def dry_run(src: Path | None = None, *, keep: bool = False) -> dict:
    """Migrate a copy of `src` (default: this home's store) with this checkout's code; `src` is only read."""
    src = Path(src if src is not None else ms.db_path()).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"no store at {src}")
    work = Path(tempfile.mkdtemp(prefix="soh-dry-run-"))
    home = work / "home"
    home.mkdir()
    copy = home / "discovery.db"
    try:
        _copy_store(src, copy)
        _copy_home(src.parent, home)
        raw = sqlite3.connect(copy)
        raw.row_factory = sqlite3.Row
        try:
            was, before = schema(raw), counts(raw)
        finally:
            raw.close()
        with _home(home):
            start = time.monotonic()
            conn = ms.connect(copy)
            took = time.monotonic() - start
            try:
                checks = invariants(conn)
                audit = ms.state_audit(conn)
                after = counts(conn)
                again = rerun(conn, was)
            finally:
                conn.close()
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    return {"source": str(src), "copy": str(copy), "kept": keep,
            "schema_from": was, "schema_to": ms.SCHEMA_VERSION,
            "seconds": round(took, 2),
            "ok": all(c.ok for c in checks) and not again,
            "invariants": [{"name": c.name, "ok": c.ok, "detail": c.detail}
                           for c in checks],
            "rerun": {t: list(v) for t, v in again.items()},
            "state_audit": {k: len(v) for k, v in audit.items()},
            "counts_before": before, "counts_after": after}


def report_text(got: dict) -> str:
    lines = [f"dry run of {got['source']}",
             f"  schema {got['schema_from']} -> {got['schema_to']} "
             f"in {got['seconds']} s, on a copy"
             + (f" kept at {got['copy']}" if got["kept"] else "")]
    for c in got["invariants"]:
        lines.append(f"  {'ok  ' if c['ok'] else 'FAIL'} {c['name']}"
                     + (f": {c['detail']}" if c["detail"] else ""))
    lines.append("  ok   rerun: a retried migration adds nothing" if not got["rerun"]
                 else f"  FAIL rerun: a retried migration changes {got['rerun']}")
    audit = got["state_audit"]
    lines.append(f"  info {audit.get('folds_differently', 0)} state(s) the "
                 f"transition table folds differently, "
                 f"{audit.get('terminal_then_open', 0)} reopened after a terminal")
    changed = {t: (got["counts_before"].get(t, 0), n)
               for t, n in got["counts_after"].items()
               if got["counts_before"].get(t, 0) != n}
    if changed:
        lines.append("  rows " + ", ".join(f"{t} {a}->{b}"
                                           for t, (a, b) in sorted(changed.items())))
    lines.append("OK: safe to deploy" if got["ok"] else "NOT OK: do not deploy")
    return "\n".join(lines)


def rerun(conn, schema_was: int) -> dict:
    """Stamp the store back to `schema_was` and migrate again: what changed. {table: (before, after)}."""
    before = counts(conn)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)",
                 (str(schema_was),))
    ms._migrate(conn)
    after = counts(conn)
    return {t: (before.get(t, 0), n) for t, n in after.items()
            if before.get(t, 0) != n}
