"""`soh discover-why REPO`: which tiers sighted a repo, and where the crowd tier lets it fall out; the store read-only. #764."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def _client(budget: int):
    from harness import github
    return github.Client(budget=budget) if budget > 0 else github.CacheOnly()


def _store(repo: str, path: str = "") -> dict:
    """The store's sightings of `repo` by source and its proposal state, read with mode=ro."""
    import sqlite3
    from pathlib import Path

    from harness import live_audit, memory_store as ms
    db = Path(path) if path else ms.db_path()
    if not db.is_file():
        return {"found": False, "why": f"no store at {db}"}
    conn = live_audit.open_readonly(db)
    try:
        row = conn.execute("SELECT id, name, registry, kind, state FROM proposals WHERE lower(name) = lower(?)",
                           (repo,)).fetchone()
        if row is None:
            return {"found": False, "why": "no proposal names it"}
        seen = {r["source"]: r["n"] for r in conn.execute(
            "SELECT source, COUNT(*) AS n FROM sightings WHERE proposal_id = ? GROUP BY source ORDER BY source",
            (row["id"],))}
    except sqlite3.Error as exc:
        return {"found": False, "why": f"store unreadable: {exc}"}
    finally:
        conn.close()
    return {"found": True, "name": row["name"], "registry": row["registry"], "kind": row["kind"],
            "sightings": seen, "state": row["state"]}


def cmd_discover_why(a) -> int:
    from harness import github, neighbors as nb
    repo = a.repo.strip().strip("/")
    if repo.count("/") != 1:
        return err(f"{a.repo!r} is not owner/name")
    store = _store(repo, a.db)
    client = _client(a.budget)
    try:
        people = nb.cohort(nb.DEFAULT_SEEDS, client=client)
    except github.GitHubError as exc:
        return err(f"the crowd could not be built: {exc}")
    depths = tuple(sorted({int(d) for d in a.depths.split(",") if d.strip()} | {nb.STAR_PAGES}))
    got = nb.why(repo, people, client, depths=depths)
    if store["found"]:
        note(f"{repo}: in the store as {store['kind']} ({store['registry'] or 'no registry'}), sighted by "
             + (", ".join(f"{s} x{n}" for s, n in store["sightings"].items()) or "no source"))
        note(f"  state: {store['state']}")
    else:
        note(f"{repo}: not in the store ({store['why']})")
    note(f"  github-crowd: {got['crowd']} members read"
         + (f", {got['unread']} with pages not cached or not fetched" if got["unread"] else "")
         + (f", {client.spent} requests" if client.spent else ""))
    for d in depths:
        mark = "  <- the sweep" if d == nb.STAR_PAGES else ""
        note(f"    {d:>3} page(s): {got['by_depth'][d]} of {got['crowd']} starred it{mark}")
    if got["positions"]:
        note(f"    positions from each member's newest star: {', '.join(map(str, got['positions']))}")
    note(f"  {got['verdict']}")
    emit(True, repo=repo, store=store, crowd=got, requests=client.spent)
    return 0
