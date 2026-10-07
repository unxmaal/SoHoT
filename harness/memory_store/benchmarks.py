"""The benchmark tables: what a sweep found, who trained on what, and what a probe saw. #491, #470."""
from __future__ import annotations

import json
import time

_FACTS = ("registry", "url", "license", "gated", "created", "updated", "size",
          "rows", "task_format", "revision", "likes", "downloads", "description")


def record_benchmark(conn, b, at: float | None = None) -> None:
    """Upsert one found benchmark by (name, lane); the facts are replaced, first_seen kept."""
    at = time.time() if at is None else float(at)
    values = [getattr(b, f) for f in _FACTS]
    conn.execute(
        f"INSERT INTO benchmarks (name, lane, {', '.join(_FACTS)}, first_seen, last_seen) "
        f"VALUES ({', '.join('?' * (len(_FACTS) + 4))}) "
        "ON CONFLICT (name, lane) DO UPDATE SET "
        + ", ".join(f"{f} = excluded.{f}" for f in _FACTS) + ", last_seen = excluded.last_seen",
        (b.name, b.lane, *values, at, at))
    conn.commit()


def benchmarks(conn, lane: str = "") -> list[dict]:
    sql = "SELECT * FROM benchmarks"
    args: tuple = ()
    if lane:
        sql, args = sql + " WHERE lane = ?", (lane,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY lane, created DESC, name", args)]


def set_training(conn, candidate: str, *, alias: str = "", cutoff: str = "",
                 cutoff_source: str = "", datasets=(), at: float | None = None,
                 lane: str = "") -> None:
    """A candidate's cutoff and declared datasets, replacing any earlier read."""
    at = time.time() if at is None else float(at)
    conn.execute(
        "INSERT INTO candidate_training (candidate, alias, lane, cutoff, cutoff_source, "
        "datasets, read_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT (candidate) DO UPDATE SET "
        "alias = excluded.alias, lane = excluded.lane, cutoff = excluded.cutoff, "
        "cutoff_source = excluded.cutoff_source, datasets = excluded.datasets, "
        "read_at = excluded.read_at",
        (candidate, alias, lane, cutoff, cutoff_source, json.dumps(list(datasets)), at))
    conn.commit()


def training(conn) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM candidate_training ORDER BY cutoff DESC, candidate"):
        row = dict(r)
        row["datasets"] = json.loads(row["datasets"] or "[]")
        out.append(row)
    return out


def record_probe(conn, *, model: str, lane: str, case_id: str, family: str,
                 outcome: str, overlap: float | None, detail: str = "",
                 at: float | None = None) -> None:
    at = time.time() if at is None else float(at)
    conn.execute(
        "INSERT INTO contamination_probes (model, lane, case_id, family, outcome, overlap, "
        "detail, at) VALUES (?,?,?,?,?,?,?,?)",
        (model, lane, case_id, family, outcome, overlap, detail[:500], at))
    conn.commit()


def probe_summary(conn, lane: str = "") -> list[dict]:
    """Per (model, lane, family), from each case's newest probe only."""
    where, args = ("WHERE p.lane = ?", (lane,)) if lane else ("", ())
    rows = conn.execute(
        "SELECT p.model, p.lane, p.family, "
        "SUM(CASE WHEN p.outcome IN ('hit', 'miss') THEN 1 ELSE 0 END) AS probed, "
        "SUM(CASE WHEN p.outcome = 'hit' THEN 1 ELSE 0 END) AS hits, "
        "SUM(CASE WHEN p.outcome = 'skipped' THEN 1 ELSE 0 END) AS skipped, "
        "SUM(CASE WHEN p.outcome = 'error' THEN 1 ELSE 0 END) AS errors, "
        "AVG(p.overlap) AS mean_overlap, MAX(p.at) AS at "
        "FROM contamination_probes p JOIN (SELECT model, case_id, MAX(id) AS id "
        "FROM contamination_probes GROUP BY model, case_id) n ON n.id = p.id "
        f"{where} GROUP BY p.model, p.lane, p.family ORDER BY p.lane, p.family, p.model",
        args)
    return [dict(r) for r in rows]
