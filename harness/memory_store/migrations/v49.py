"""Schema 49: a by-hand adoption is scoped to the machine whose votes made it. #485."""
from __future__ import annotations

import json
from collections import Counter

from harness.memory_store.schema import _columns

VERSION = 49

_COLUMNS = (("all_machines", "INTEGER NOT NULL DEFAULT 0"), ("votes", "INTEGER"),
            ("agreement", "REAL"), ("forced", "INTEGER NOT NULL DEFAULT 0"),
            ("cost", "TEXT NOT NULL DEFAULT '{}'"))


def columns(conn) -> None:
    have = _columns(conn, "adoptions")
    for col, ddl in _COLUMNS:
        if col not in have:
            conn.execute(f"ALTER TABLE adoptions ADD COLUMN {col} {ddl}")


def _one(ids) -> int | None:
    ids = {i for i in ids if i is not None}
    return ids.pop() if len(ids) == 1 else None


def data(conn) -> None:
    from harness import human
    got = conn.execute("SELECT value FROM meta WHERE key = 'candidate_guesses'"
                       ).fetchone()
    guesses = json.loads(got[0]) if got and got[0] else []
    seen = {g.get("adoption") for g in guesses if isinstance(g, dict)}
    for a in conn.execute(
            "SELECT a.id, a.lane, a.machine_id, a.run_id, c.spec, c.receipt_key, "
            "p.name AS proposal FROM adoptions a "
            "JOIN candidates c ON c.id = a.candidate_id "
            "LEFT JOIN proposals p ON p.id = c.proposal_id "
            "WHERE a.how = 'by-hand' AND a.all_machines = 0 ORDER BY a.id").fetchall():
        votes = conn.execute(
            "SELECT case_id, left_candidate, right_candidate, winner, run, "
            "machine_id FROM human_votes WHERE lane = ? AND "
            "(left_candidate = ? OR right_candidate = ?)",
            (a["lane"], a["receipt_key"], a["receipt_key"])).fetchall()
        mid = _one(v["machine_id"] for v in votes)
        if mid is None:
            paths = sorted({v["run"] for v in votes if v["run"]})
            marks = ",".join("?" * len(paths)) or "NULL"
            mid = _one(r[0] for r in conn.execute(
                f"SELECT machine_id FROM runs WHERE path IN ({marks})", paths))
        if mid is None and a["run_id"] is not None:
            mid = _one(r[0] for r in conn.execute(
                "SELECT machine_id FROM runs WHERE id = ?", (a["run_id"],)))
        if mid is None:
            mid = a["machine_id"]
            if a["id"] not in seen:
                guesses.append({"adoption": a["id"], "lane": a["lane"],
                                "proposal": a["proposal"] or "",
                                "spec": a["spec"], "machine": mid,
                                "from": "the adopt verdict's machine; no vote "
                                        "or judged run names one"})
        tallies: dict[tuple, Counter] = {}
        for v in votes:
            key = (v["case_id"], v["left_candidate"], v["right_candidate"])
            tallies.setdefault(key, Counter())[v["winner"]] += 1
        n, agree = human.agreement(list(tallies.values()))
        conn.execute("UPDATE adoptions SET machine_id = ?, votes = ?, "
                     "agreement = ? WHERE id = ?",
                     (mid, n if votes else None, agree, a["id"]))
    if guesses or got:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('candidate_guesses', ?)",
                     (json.dumps(guesses, sort_keys=True),))
    conn.commit()
