"""The candidates a ranked list may hold: a runner, a load that fits, dependencies under the cap, a family not demoted. #2165."""
from __future__ import annotations

from harness import lanes, reasons
from harness import memory_store as ms

RUNNER, WINDOW, DEPENDENCY, FAMILY, REFETCH = "runner", "window", "dependency", "family", "refetch"
#: What a recorded prefilter verdict starts its detail with, so the funnel and a reader know whose word it is.
SAID = "prefilter: "
_REASON = {RUNNER: reasons.HARNESS, WINDOW: reasons.MACHINE, DEPENDENCY: reasons.LIMIT, FAMILY: reasons.CANDIDATE,
           REFETCH: reasons.LIMIT}


def _stored_size(conn):
    """A sizer for fetching.dependency_gap that reads only what inspect stored: -1 for a repo it never sized."""
    def size(repo: str) -> int:
        got = conn.execute("SELECT size_bytes FROM proposals WHERE name = ? OR resolved = ? ORDER BY id LIMIT 1",
                           (repo, repo)).fetchone()
        return int((got["size_bytes"] if got else 0) or 0) or -1
    return size


def _why(conn, row: dict, standing, sizer) -> tuple[str, str] | None:
    """(kind, why) `row` is not testable here, or None; the first of runner, load, dependencies, refetch, family."""
    from harness import fetching, memory, methods, refetch
    gap = fetching.runnable_gap(conn, row)
    if gap:
        return RUNNER, gap[1]
    name = row.get("resolved") or row["name"]
    lane = row.get("lane") or ""
    target = methods.weights_of(row["name"]) if methods.is_method(row["name"]) else name
    need = int(row.get("size_bytes") or 0) / fetching.GIB
    most = memory.standing_gb() + memory.pinned_gb()
    if need > most + 1e-9:
        return WINDOW, (f"{target} needs {need:.1f} GiB, more than the {max(most, 0.0):.1f} GiB a load can get here "
                        f"with the interactive server's pinned models released")
    if target:
        own = fetching.plan(target, int(row.get("size_bytes") or 0) or fetching.MAX_DOWNLOAD, free=1 << 60)
        if own.reason == reasons.LIMIT:
            return DEPENDENCY, f"{target}: {own.why}"
        gap_dep = fetching.dependency_gap(conn, target, free=1 << 60, sizer=sizer)
        if gap_dep and gap_dep[0].reason == reasons.LIMIT:
            return DEPENDENCY, gap_dep[1]
        held = refetch.holds(conn, target, "the prefilter", row["name"])
        if held:
            return REFETCH, held
    got, said = standing.demotion(row, lanes.canonical(lane))
    if got < 0:
        return FAMILY, said
    return None


def split(conn, rows: list[dict], *, standing=None) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    """`rows` less those no screen here could run, in order, and {name: (kind, why)} for each one left out."""
    if not rows:
        return rows, {}
    if standing is None:
        from harness import family
        standing = family.standing(conn)
    sizer = _stored_size(conn)
    kept, held = [], {}
    for r in rows:
        got = _why(conn, r, standing, sizer)
        if got:
            held[r["name"]] = got
        else:
            kept.append(r)
    return kept, held


def said(held: tuple[str, str]) -> str:
    """One held row's (kind, why) as a sentence."""
    return f"{held[0]}: {held[1]}"


def record(conn, held: dict[str, tuple[str, str]]) -> None:
    """Each row left out keeps its place as a queued fetch verdict naming why, which `soh funnel` reads."""
    for name, (kind, why) in held.items():
        ms.decide_or_skip(conn, name, "queued", tier=ms.FETCH, detail=f"{SAID}{said((kind, why))}"[:600],
                          reason=_REASON[kind], commit=False)
    conn.commit()
