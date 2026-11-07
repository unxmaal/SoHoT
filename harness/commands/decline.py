"""`soh decline REPO "<owner: why>"`: the owner declines a candidate by name, terminal and never reopened by a retest. #1564."""
from __future__ import annotations

from harness.commands.common import emit, err, note

#: Who the verdict names as its judge.
JUDGE = "owner"


def decline(conn, repo: str, said: str) -> dict:
    """Write the owner's decline through the transitions path; ValueError when it has no who and why or no proposal."""
    from harness import memory_store as ms
    from harness import reasons
    said = (said or "").strip()
    if not said:
        raise ValueError('a decline names who declined it and why: soh decline szwagros/Lens-Turbo "owner: not wanted"')
    row = conn.execute("SELECT name, state FROM proposals WHERE name = ? OR resolved = ? ORDER BY id LIMIT 1",
                       (repo, repo)).fetchone()
    if row is None:
        raise ValueError(f"no proposal named {repo}: discovery has not sighted it, so there is nothing to decline")
    vid = ms.decide(conn, row["name"], "declined", tier=ms.ADOPT, reason=reasons.OWNER, judge=JUDGE,
                    detail=f"declined by the owner: {said}")
    return {"name": row["name"], "was": row["state"], "verdict": vid, "said": said}


def cmd_decline(a) -> int:
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        try:
            got = decline(conn, a.repo, " ".join(a.said))
        except (ValueError, ms.IllegalTransition) as exc:
            return err(str(exc))
    finally:
        conn.close()
    note(f"declined {got['name']} (was {got['was'] or 'new'}), verdict {got['verdict']}: {got['said']}. "
         "Discovery, fetch and screen skip it and its runner bases; no retest reopens it.")
    emit(**got)
    return 0
