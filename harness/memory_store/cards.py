"""Model-card facts on proposals, and the lineage between them."""
from __future__ import annotations

import json


#: The card-fact columns, on a store older than the DDL. #414.
CARD_COLUMNS = ("hf_task", "library", "card_tags", "attaches_to",
                "runtime_needed", "lane_source", "card_read")


def set_card(conn, name: str, card, read: str = "card") -> bool:
    """Write a card's facts and its lineage rows; False if no such proposal.

    The writer is the inspect tier, from the registry's own fields. Lineage is
    replaced, not merged: a card that dropped a parent no longer has it. #414.
    """
    from harness import lanes
    row = conn.execute("SELECT id, lane FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row:
        return False
    same = bool(card.lane) and lanes.canonical(row["lane"]) == \
        lanes.canonical(card.lane)
    conn.execute(
        "UPDATE proposals SET hf_task = ?, library = ?, card_tags = ?, "
        "attaches_to = ?, runtime_needed = ?, card_read = ?, "
        "lane_source = CASE WHEN ? THEN ? ELSE lane_source END WHERE id = ?",
        (card.task, card.library, json.dumps(list(card.tags)),
         card.attaches_to, card.runtime_needed, read,
         1 if same else 0, card.lane_source, row["id"]))
    if getattr(card, "category", ""):
        conn.execute("UPDATE proposals SET category = ? WHERE id = ?",
                     (card.category, row["id"]))
    conn.execute("DELETE FROM lineage WHERE proposal_id = ?", (row["id"],))
    for parent, kind in card.parents:
        conn.execute("INSERT OR IGNORE INTO lineage (proposal_id, parent, kind) "
                     "VALUES (?,?,?)", (row["id"], parent, kind))
    conn.commit()
    return True


def parents_of(conn, names) -> dict[str, list[tuple[str, str]]]:
    """name -> [(parent, kind)] from the lineage table. #414."""
    names = list(dict.fromkeys(names))
    out: dict = {n: [] for n in names}
    for i in range(0, len(names), 500):
        chunk = names[i:i + 500]
        for r in conn.execute(
                "SELECT p.name, l.parent, l.kind FROM lineage l "
                "JOIN proposals p ON p.id = l.proposal_id "
                f"WHERE p.name IN ({','.join('?' * len(chunk))}) "
                "ORDER BY l.id", chunk):
            out[r["name"]].append((r["parent"], r["kind"]))
    return out


def card_of(conn, name: str) -> dict | None:
    """The card facts an engine is chosen by: library, tags, parents. #467."""
    row = conn.execute("SELECT library, card_tags, hf_task FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row:
        return None
    return {"library": row["library"], "card_tags": row["card_tags"], "hf_task": row["hf_task"],
            "parents": parents_of(conn, [name])[name]}


def with_lineage(conn, rows: list[dict]) -> list[dict]:
    """Each row with `parents`: its [(parent, kind)] lineage. #414."""
    got = parents_of(conn, [r["name"] for r in rows])
    for r in rows:
        r["parents"] = got.get(r["name"], [])
    return rows
