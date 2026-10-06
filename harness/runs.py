"""Eval runs and their result rows, in the store. #410.

evals.run writes a run and its rows here as it finishes; results.json beside
the artifacts is an export for people. Every reader asks these tables, never
the runs directory by name, mtime or "newest receipt".
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

from harness import reasons

#: What a stored run is when its receipt does not say.
MEASURE, SCREEN = "measure", "screen"


@contextmanager
def store(conn=None):
    """`conn`, or a connection opened and closed around the block."""
    if conn is not None:
        yield conn
        return
    from harness import memory_store as ms
    opened = ms.connect()
    try:
        yield opened
    finally:
        opened.close()


def path_key(path) -> str:
    """A run's identity: its path under the runs dir, else its absolute path."""
    from harness import paths
    p = Path(path).expanduser()
    root = paths.runs()
    if not p.is_absolute():
        p = root / p
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p.resolve())


def _epoch(generated) -> float | None:
    try:
        return time.mktime(time.strptime(str(generated), "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError, OverflowError):
        return None


def _split_case(case_id: str) -> tuple[str, int]:
    base, _, n = (case_id or "").partition("#")
    return base, int(n) if n.isdigit() else 1


def machine_for(conn, env: dict) -> int | None:
    """The machines row a receipt's environment names, inserted if new."""
    from harness import machine
    env = env or {}
    parts = [str(env.get(k) or "") for k in ("hw_model", "os", "arch")]
    if not any(parts):
        return None
    if parts[0] and not machine.os_family(parts[1]):
        # No OS named: the one machine with that board, as the merge decides.
        same = conn.execute("SELECT id FROM machines WHERE hw_model = ? AND "
                            "arch = ? AND os != ''", (parts[0], parts[2])).fetchall()
        if len(same) == 1:
            return same[0]["id"]
    # The same identity remember_machine writes, never platform.platform(). #415.
    fingerprint = machine.fingerprint(*parts)
    now = time.time()
    conn.execute(
        "INSERT OR IGNORE INTO machines (fingerprint, hw_model, os, arch, "
        "memory_gb, first_seen, last_seen) VALUES (?,?,?,?,?,?,?)",
        (fingerprint, parts[0], parts[1], parts[2],
         float(env.get("memory_gb") or 0), now, now))
    return conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                        (fingerprint,)).fetchone()["id"]


def here(conn) -> list[int]:
    """This machine's id, by fingerprint; [] before it has a row. #331, #415.

    One machine is one row now, so freshness and adoption no longer stand in
    hw_model for identity. hw_model stays a column for comparability.
    """
    from harness import memory_store as ms
    mid = ms.machine_row(conn)
    return [mid] if mid is not None else []


def _in(column: str, ids) -> tuple[str, tuple]:
    ids = tuple(ids)
    if not ids:
        return " AND 1 = 0", ()
    return f" AND {column} IN ({','.join('?' * len(ids))})", ids


def _candidate(conn, key: str, spec: str, lane: str) -> int | None:
    """The candidates row a result row belongs to, through the stored mapping."""
    from harness import candidates as C
    from harness import memory_store as ms
    if spec:
        return C.ensure(conn, ms._legacy_spec(spec), key=key, lane=lane)
    rows = conn.execute("SELECT id, spec FROM candidates WHERE receipt_key = ?",
                        (key,)).fetchall()
    if not rows:
        return None
    # A spec without options is the candidate; `,temperature=0` is a variant.
    best = min(rows, key=lambda r: (r["spec"] != key, "," in r["spec"], r["id"]))
    return best["id"]


def record(conn, path, data: dict, *, at: float | None = None) -> int | None:
    """Store one receipt (the results.json shape) as a run and its rows.

    Idempotent by path: recording the same run again replaces its rows and
    keeps its id, so verdicts that cite it stay linked. None when `data` is
    not an eval receipt (no case rows).
    """
    rows = [r for r in (data.get("rows") or [])
            if isinstance(r, dict) and "case_id" in r and "passed" in r]
    if not rows:
        return None
    receipt = data.get("receipt") or {}
    env = data.get("environment") or {}
    specs = data.get("specs") or {}
    lane = str(receipt.get("modality") or "").strip().lower()
    key = path_key(path)
    when = at if at is not None else _epoch(data.get("generated"))
    values = (lane, str(receipt.get("tier") or MEASURE),
              machine_for(conn, env), when, int(receipt.get("repeat") or 1),
              str(receipt.get("cases_digest") or ""), json.dumps(receipt),
              json.dumps(env), json.dumps(specs))
    conn.execute(
        "INSERT OR IGNORE INTO runs (path, lane, tier, machine_id, "
        "generated_at, repeat_count, cases_digest, receipt, environment, "
        "specs, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (key, *values, time.time()))
    conn.execute(
        "UPDATE runs SET lane = ?, tier = ?, machine_id = ?, generated_at = ?, "
        "repeat_count = ?, cases_digest = ?, receipt = ?, environment = ?, "
        "specs = ? WHERE path = ?", (*values, key))
    run_id = conn.execute("SELECT id FROM runs WHERE path = ?",
                          (key,)).fetchone()["id"]
    conn.execute("DELETE FROM results WHERE run_id = ?", (run_id,))
    ids: dict[str, int | None] = {}
    for seq, r in enumerate(rows):
        name = str(r.get("candidate") or "")
        if name not in ids:
            ids[name] = _candidate(conn, name, specs.get(name, ""), lane)
        repeat = _split_case(str(r.get("case_id") or ""))[1]
        cls = r.get("failure_class")
        if cls is None and not r.get("passed"):
            # A receipt from before runners set a class: read once, here. #408.
            cls = reasons.legacy_class(str(r.get("detail") or ""),
                                       specs.get(name, ""))
        conn.execute(
            "INSERT INTO results (run_id, seq, candidate_id, candidate, "
            "case_id, repeat_index, passed, seconds, peak_kb, detail, metrics, "
            "warnings, artifact, failure_class, hit_limit) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, seq, ids[name], name, str(r.get("case_id") or ""), repeat,
             1 if r.get("passed") else 0, float(r.get("seconds") or 0.0),
             int(r.get("peak_kb") or 0), str(r.get("detail") or ""),
             json.dumps(r.get("metrics") or {}),
             json.dumps(r.get("warnings") or []),
             None if r.get("artifact") is None else str(r["artifact"]),
             cls or "", str(r.get("limit") or "")))
    conn.commit()
    return run_id


def get(conn, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def at(conn, path) -> dict | None:
    """The run stored for the directory a caller named, or None."""
    row = conn.execute("SELECT * FROM runs WHERE path = ?",
                       (path_key(path),)).fetchone()
    return dict(row) if row else None


def rows(conn, run_id: int, candidate_id: int | None = None) -> list[dict]:
    """A run's result rows in the order they ran, as results.json held them."""
    sql = "SELECT * FROM results WHERE run_id = ?"
    args: tuple = (run_id,)
    if candidate_id is not None:
        sql += " AND candidate_id = ?"
        args += (candidate_id,)
    out = []
    for r in conn.execute(sql + " ORDER BY seq", args).fetchall():
        out.append({"case_id": r["case_id"], "candidate": r["candidate"],
                    "passed": bool(r["passed"]), "seconds": r["seconds"],
                    "peak_kb": r["peak_kb"], "detail": r["detail"],
                    "artifact": r["artifact"],
                    "warnings": json.loads(r["warnings"] or "[]"),
                    "metrics": json.loads(r["metrics"] or "{}"),
                    "failure_class": r["failure_class"], "limit": r["hit_limit"],
                    "candidate_id": r["candidate_id"]})
    return out


def summarize(result_rows: list[dict]) -> dict:
    """The per-candidate summary, computed from stored rows."""
    from evals.core import Result, summarize as roll_up
    return roll_up([Result(case_id=r["case_id"], candidate=r["candidate"],
                           passed=r["passed"], seconds=r["seconds"],
                           peak_kb=r["peak_kb"], detail=r["detail"],
                           artifact=r["artifact"], warnings=r["warnings"],
                           metrics=r["metrics"],
                           failure_class=r.get("failure_class") or "",
                           limit=r.get("limit") or "") for r in result_rows])


def receipt(conn, run) -> dict | None:
    """A stored run in the results.json shape: receipt, specs, summary, rows."""
    run = get(conn, run) if isinstance(run, int) else run
    if not run:
        return None
    got = rows(conn, run["id"])
    generated = (time.strftime("%Y-%m-%dT%H:%M:%S",
                               time.localtime(run["generated_at"]))
                 if run["generated_at"] is not None else "")
    return {"run_id": run["id"], "path": run["path"], "generated": generated,
            "environment": json.loads(run["environment"] or "{}"),
            "receipt": json.loads(run["receipt"] or "{}"),
            "specs": json.loads(run["specs"] or "{}"),
            "summary": summarize(got), "rows": got}


def receipt_at(conn, path) -> dict | None:
    """The stored receipt for the directory a caller named, or None."""
    return receipt(conn, at(conn, path))


def find(conn, *, lane: str = "", tier: str = "", machines=None,
         candidate_id=None) -> list[dict]:
    """Stored runs, newest first by the time the receipt says it ran."""
    sql = "SELECT r.* FROM runs r WHERE 1 = 1"
    args: list = []
    if lane:
        sql += " AND r.lane = ?"
        args.append(lane)
    if tier:
        sql += " AND r.tier = ?"
        args.append(tier)
    if machines is not None:
        clause, ids = _in("r.machine_id", machines)
        sql += clause
        args.extend(ids)
    if candidate_id is not None:
        sql += (" AND EXISTS (SELECT 1 FROM results x WHERE x.run_id = r.id "
                "AND x.candidate_id = ?)")
        args.append(candidate_id)
    sql += " ORDER BY COALESCE(r.generated_at, 0) DESC, r.id DESC"
    return [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]


def newest(conn, **where) -> dict | None:
    got = find(conn, **where)
    return got[0] if got else None


def row_for(conn, run_id: int, candidate_id: int) -> dict:
    """One candidate's summary row in one run, by candidate id; {} if absent."""
    mine = rows(conn, run_id, candidate_id)
    if not mine:
        return {}
    key, row = next(iter(summarize(mine).items()))
    return {**row, "candidate": key, "run_id": run_id}


def age_days(run: dict | None, now: float | None = None) -> float | None:
    if not run or run.get("generated_at") is None:
        return None
    return max(0.0, ((now or time.time()) - run["generated_at"]) / 86400.0)


def lanes(conn) -> set[str]:
    """Lanes with at least one stored result row."""
    return {r["lane"] for r in conn.execute(
        "SELECT DISTINCT r.lane FROM runs r JOIN results x ON x.run_id = r.id "
        "WHERE r.lane != ''").fetchall()}


def keys(conn) -> set[str]:
    """Every receipt key any stored run measured."""
    return {r["candidate"] for r in conn.execute(
        "SELECT DISTINCT candidate FROM results").fetchall()}


def keys_in(conn, run_id: int) -> set[str]:
    return {r["candidate"] for r in conn.execute(
        "SELECT DISTINCT candidate FROM results WHERE run_id = ?",
        (run_id,)).fetchall()}


def first_seen(conn) -> list[dict]:
    """Per (lane, receipt key), the earliest time a stored run measured it."""
    return [dict(r) for r in conn.execute(
        "SELECT r.lane, x.candidate, MIN(r.generated_at) AS at FROM results x "
        "JOIN runs r ON r.id = x.run_id WHERE r.generated_at IS NOT NULL "
        "GROUP BY r.lane, x.candidate").fetchall()]


def peak_kb(conn, key: str, machines=None) -> int:
    """The largest peak any stored row measured under a receipt key."""
    sql = ("SELECT MAX(x.peak_kb) AS m FROM results x JOIN runs r "
           "ON r.id = x.run_id WHERE x.candidate = ?")
    args: tuple = (key,)
    if machines is not None:
        clause, ids = _in("r.machine_id", machines)
        sql += clause
        args += ids
    got = conn.execute(sql, args).fetchone()
    return int(got["m"] or 0) if got else 0


def summaries(conn, *, tier: str = MEASURE, lane: str = ""):
    """(run, summary) for every stored run of a tier, newest first."""
    for run in find(conn, tier=tier, lane=lane):
        got = rows(conn, run["id"])
        if got:
            yield run, summarize(got), got


def backfill(conn, root=None) -> dict:
    """Import every runs/**/results.json once; idempotent. Reads files only.

    Returns counts, and lists what could not be recorded rather than
    guessing at it.
    """
    from harness import candidates as C
    from harness import memory_store as ms
    from harness import paths, screen, winners

    counts = {"runs": 0, "results": 0, "unlinked_results": 0,
              "not_eval_receipts": [], "unreadable": [], "no_receipt": [],
              "verdicts_linked": 0}
    root = Path(root) if root is not None else paths.runs()
    found = sorted(root.rglob("results.json")) if root.is_dir() else []
    # What a lane serves often ran before receipts carried a specs map.
    for lane, served in sorted(winners.typed().items()) if found else ():
        try:
            C.ensure(conn, screen.candidate_for(lane, served, conn=conn)
                     or served, lane=lane)
        except Exception:  # noqa: BLE001
            pass
    for f in found:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            counts["unreadable"].append(str(f.parent.relative_to(root)))
            continue
        run_id = record(conn, f.parent, data if isinstance(data, dict) else {})
        if run_id is None:
            counts["not_eval_receipts"].append(str(f.parent.relative_to(root)))
            continue
        counts["runs"] += 1
    if root.is_dir():
        have = {Path(str(f.parent)).resolve() for f in found}
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            if d.resolve() not in have and not any(
                    h.is_relative_to(d.resolve()) for h in have):
                counts["no_receipt"].append(d.name)
    counts["results"] = conn.execute(
        "SELECT COUNT(*) AS n FROM results").fetchone()["n"]
    counts["unlinked_results"] = conn.execute(
        "SELECT COUNT(*) AS n FROM results WHERE candidate_id IS NULL"
    ).fetchone()["n"]
    for v in conn.execute("SELECT id, run_path FROM verdicts WHERE "
                          "run_path != '' AND run_id IS NULL").fetchall():
        for where in ms.resolved_run_paths(v["run_path"]):
            run = at(conn, where)
            if run:
                conn.execute("UPDATE verdicts SET run_id = ? WHERE id = ?",
                             (run["id"], v["id"]))
                counts["verdicts_linked"] += 1
                break
    conn.commit()
    return counts
