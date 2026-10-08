"""Migration helpers that import the legacy JSON files and merge duplicate machines."""
from __future__ import annotations

from pathlib import Path
import json
import time

from harness import paths, store
from harness.memory_store.machines import remember_machine
from harness.memory_store.schema import _columns


def attribute_sightings(conn) -> dict:
    """Schema 38: give a legacy sighting the one machine the store shows could
    have recorded it, else leave it unknown. #450.

    Evidence of a machine is a run its receipt names or its machines row; a
    machine whose earliest evidence is later than the sighting did not sweep
    it. Runs with no machine name nobody and count for nobody.
    """
    first: dict[int, float] = {}
    for sql in ("SELECT machine_id AS m, MIN(generated_at) AS t FROM runs "
                "WHERE machine_id IS NOT NULL AND generated_at IS NOT NULL "
                "GROUP BY machine_id",
                "SELECT id AS m, first_seen AS t FROM machines"):
        for r in conn.execute(sql).fetchall():
            if r["t"] is not None:
                first[r["m"]] = min(first.get(r["m"], r["t"]), r["t"])
    counts = {"assigned": 0, "unknown": 0, "by_machine": {}}
    for s in conn.execute("SELECT id, seen_at FROM sightings "
                          "WHERE machine_id IS NULL").fetchall():
        could = [m for m, t in first.items() if t <= s["seen_at"]]
        if len(could) != 1:
            counts["unknown"] += 1
            continue
        conn.execute("UPDATE sightings SET machine_id = ? WHERE id = ?",
                     (could[0], s["id"]))
        counts["assigned"] += 1
        counts["by_machine"][could[0]] = counts["by_machine"].get(could[0], 0) + 1
    conn.commit()
    return counts


def _machine_fk_tables(conn) -> list[str]:
    """Every table with a machine_id column, so a merge misses none. #415."""
    if store.backend() == store.POSTGRES:
        names = [r["table_name"] for r in conn.execute(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE column_name = 'machine_id'")]
    else:
        names = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        names = [n for n in names if "machine_id" in _columns(conn, n)]
    return sorted(names)


def merge_duplicate_machines(conn) -> dict:
    """Fold machines rows whose fingerprint is now one into the oldest. #415.

    Every machine_id is repointed and each fold is a machine_merges row.
    Returns {"merged": n, "repointed": {table: rows}}.
    """
    from harness import machine as _machine
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM machines ORDER BY id").fetchall()]
    groups: dict[str, list[dict]] = {}
    for r in rows:
        fp = _machine.fingerprint(r["hw_model"], r["os"], r["arch"]) \
            if (r["hw_model"] or r["os"] or r["arch"]) else r["fingerprint"]
        groups.setdefault(fp, []).append(r)
    # A receipt that named no OS: the one machine with that board, if only one.
    for fp in [f for f, m in groups.items()
               if m[0]["hw_model"] and not _machine.os_family(m[0]["os"])]:
        hw, arch = groups[fp][0]["hw_model"], groups[fp][0]["arch"]
        homes = [f for f, m in groups.items() if f != fp
                 and m[0]["hw_model"] == hw and m[0]["arch"] == arch]
        if len(homes) == 1:
            groups[homes[0]] = sorted(groups[homes[0]] + groups.pop(fp),
                                      key=lambda r: r["id"])
    tables = _machine_fk_tables(conn)
    out: dict = {"merged": 0, "repointed": dict.fromkeys(tables, 0)}
    now = time.time()
    for fp, members in groups.items():
        keep, rest = members[0], members[1:]
        for r in rest:
            moved = {}
            for t in tables:
                n = conn.execute(f"UPDATE {t} SET machine_id = ? "
                                 f"WHERE machine_id = ?",
                                 (keep["id"], r["id"])).rowcount
                moved[t] = n
                out["repointed"][t] += n
            conn.execute(
                "INSERT INTO machine_merges (from_id, from_fingerprint, "
                "into_id, repointed, merged_at) VALUES (?,?,?,?,?)",
                (r["id"], r["fingerprint"], keep["id"],
                 json.dumps(moved, sort_keys=True), now))
            conn.execute("DELETE FROM machines WHERE id = ?", (r["id"],))
            out["merged"] += 1
        if keep["fingerprint"] != fp or rest:
            # The newest probe that said anything describes the machine now.
            recent = sorted(members, key=lambda r: (-r["last_seen"], -r["id"]))

            def latest(col, recent=recent):
                return next((r[col] for r in recent if r[col]), recent[0][col])
            conn.execute(
                "UPDATE machines SET fingerprint = ?, os = ?, first_seen = ?, "
                "last_seen = ?, memory_gb = ?, accelerator = ?, runtimes = ?, "
                "ceiling_gb = ?, versions = ? WHERE id = ?",
                (fp, latest("os"), min(r["first_seen"] for r in members),
                 recent[0]["last_seen"], latest("memory_gb"),
                 latest("accelerator"), latest("runtimes"), latest("ceiling_gb"),
                 next((r["versions"] for r in recent
                       if r.get("versions") not in (None, "", "{}")), "{}"),
                 keep["id"]))
    return out


def import_memory_limits_json(conn, path: Path | None = None) -> int:
    """memory-limits.json's ramp runs as memory_limits rows; the file is then dead. #415."""
    from harness import machine as _machine, ramp
    path = Path(path) if path is not None else paths.home() / "memory-limits.json"
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for old_fp, reports in (got.items() if isinstance(got, dict) else ()):
        parts = str(old_fp).split("/")
        fp = (_machine.fingerprint(*parts) if len(parts) == 3 else str(old_fp))
        row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                           (fp,)).fetchone()
        if row:
            mid = row["id"]
        else:
            hw, os_, arch = (parts + ["", "", ""])[:3] if len(parts) == 3 \
                else ("", "", "")
            mid = remember_machine(conn, {
                "fingerprint": fp, "hw_model": hw, "os": os_, "arch": arch})
        for report in (reports if isinstance(reports, list) else [reports]):
            if isinstance(report, dict) and not conn.execute(
                    "SELECT 1 FROM memory_limits WHERE machine_id = ? "
                    "AND report = ?",
                    (mid, json.dumps(report, sort_keys=True))).fetchone():
                ramp.save(conn, report, mid)
                n += 1
    return n


#: Files under a home that a migration step imports, besides queue/jobs and runs. #478.
LEGACY_FILES = ("human-verdicts.json", "discovery-state.json", "gguf-sources.json",
                "memory-limits.json", "discovery-sources.json",
                "cache/github/hf-sizes.json")


def import_human_verdicts_json(conn, path: Path | None = None) -> int:
    """Backfill human_votes from the retired human-verdicts.json. Read-only."""
    path = Path(path) if path is not None else paths.home() / "human-verdicts.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        at = path.stat().st_mtime
    except (OSError, ValueError):
        return 0
    n = 0
    # A retried migration finds earlier imports; a vote cast twice is two. #496.
    seen: dict[tuple, int] = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not r.get("lane") or not r.get("case"):
            continue
        lo, hi = sorted((r.get("left") or "", r.get("right") or ""))
        vote = (r["lane"], r["case"], lo, hi, r.get("winner") or "",
                r.get("shown_first") or "")
        seen[vote] = seen.get(vote, 0) + 1
        if conn.execute(
                "SELECT COUNT(*) FROM human_votes WHERE lane = ? AND case_id = ? "
                "AND left_candidate = ? AND right_candidate = ? AND winner = ? "
                "AND shown_first = ? AND run = '' AND voter = ''",
                vote).fetchone()[0] >= seen[vote]:
            continue
        # The file kept no run, voter, machine or time; mtime bounds the time.
        conn.execute(
            "INSERT INTO human_votes (lane, run, case_id, left_candidate, "
            "right_candidate, winner, shown_first, voter, machine_id, at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["lane"], "", r["case"], lo, hi, r.get("winner") or "",
             r.get("shown_first") or "", "", None, at))
        n += 1
    return n


def import_discovery_state_json(conn, path: Path | None = None) -> int:
    """Backfill sources from the retired discovery-state.json. Read-only. #416."""
    from harness import feeds
    path = (Path(path) if path is not None
            else paths.home() / "discovery-state.json")
    try:
        fetched = json.loads(path.read_text(encoding="utf-8")).get("fetched")
    except (OSError, ValueError, AttributeError):
        return 0
    known = {s.name: s for s in feeds.DEFAULT_SOURCES}
    n = 0
    for name, when in (fetched or {}).items():
        if not isinstance(when, (int, float)) or isinstance(when, bool):
            continue
        s = known.get(name)
        conn.execute(
            "INSERT INTO sources (name, kind, url, enabled, retired) VALUES (?,?,?,?,?) "
            "ON CONFLICT (name) DO NOTHING",
            (name, s.kind if s else "", s.url if s else "",
             int(s.enabled) if s else 0, "" if s else feeds.retired_reason(name)))
        cur = conn.execute(
            "UPDATE sources SET last_read_at = ?, last_attempt_at = "
            "COALESCE(last_attempt_at, ?), last_status = CASE WHEN "
            "last_status = '' THEN 'ok' ELSE last_status END WHERE name = ? "
            "AND (last_read_at IS NULL OR last_read_at < ?)",
            (float(when), float(when), name, float(when)))
        n += cur.rowcount or 0
    return n


def retire_unread_sources(conn) -> int:
    """Disable each live source row no tier can read (no kind, no url), recording why. #625."""
    from harness import feeds
    n = 0
    for (name,) in conn.execute(
            "SELECT name FROM sources WHERE retired = '' AND kind = '' AND url = ''").fetchall():
        n += conn.execute("UPDATE sources SET enabled = 0, retired = ? WHERE name = ?",
                          (feeds.retired_reason(name), name)).rowcount or 0
    return n


def import_size_cache_lanes(conn, path: Path | None = None) -> int:
    """Lanes the HF size cache carried, onto proposals that have none. #416."""
    from harness import lanes
    path = (Path(path) if path is not None
            else paths.home() / "cache" / "github" / "hf-sizes.json")
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for name, hit in (cache.items() if isinstance(cache, dict) else ()):
        lane = lanes.canonical(hit.get("lane") or "") if isinstance(hit, dict) else ""
        if lane:
            cur = conn.execute("UPDATE proposals SET lane = ? WHERE name = ? "
                               "AND lane = ''", (lane, name))
            n += cur.rowcount or 0
    return n
