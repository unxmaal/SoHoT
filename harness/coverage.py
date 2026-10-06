"""What discovery never saw. Issue #99, assumption F1.

Extraction precision -- 0.45 from the recap, issue #49 -- measures the quality
of what gets CAUGHT. Nothing here has ever measured what is never seen at all,
and those are different numbers.

THE PROBE, and it needs no models and no network: take the things this project
actually adopted, and ask which configured source ever produced each. Anything
adopted that no source ever surfaced is a coverage hole with a name, and the
names are the useful part -- "we read three subreddits and a release feed" is a
list of sources, not a measurement of reach.

WHAT COUNTS AS ADOPTED is read from three places that cannot drift from the
truth, because each is what the thing itself says:

    served      the gateway config's upstream ids -- what this machine runs
    measured    candidates a stored result row ran as -- what was evaluated
    default     the typed lane defaults -- what a bare command reaches for

A THING IS A PROPOSAL: a candidates row names the proposal it runs (#407), so a
voice or a run option of one model is that one model. A candidate with no
proposal is named by its spec and is a hole; a result row with no candidate is
counted as unlinked, never matched by spelling. #429.

A THING FOUND ONLY AFTER IT WAS ADOPTED DID NOT LEAD US TO IT. The store's
first sighting is compared against the earliest receipt naming it, so a source
that turned it up a month later gets no credit for the find. That is the
difference between a source that works and a source that eventually agrees.
"""
from __future__ import annotations


#: Sources that are not discovery: they record what a later tier did with a
#: name, so crediting them with finding it would be circular. `inspect` writes
#: what it read, `installed` is the seed list of what we already run, and
#: `lh discover --gap` is this project asking itself what it lacks.
NOT_DISCOVERY = {"inspect", "installed", "lh discover --gap"}


def aliases(config=None) -> dict[str, str]:
    """This machine's gateway alias -> the upstream id it actually serves.

    AN ALIAS IS OUR OWN NAMING and no source can propose one. Asking whether a
    feed ever surfaced `local-large` is asking whether strangers guessed a name
    we invented; the fair question is whether anything surfaced
    `mlx-community/Qwen2.5-7B-Instruct-4bit`, which is what that alias runs.
    """
    import os
    from pathlib import Path
    try:
        import yaml
    except ImportError:      # pragma: no cover - yaml is a hard dependency
        return {}
    root = Path(__file__).resolve().parent.parent
    config = config or Path(os.environ.get("GATEWAY_CONFIG",
                                           root / "gateway" / "config.yaml"))
    try:
        data = yaml.safe_load(Path(config).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for entry in data.get("model_list") or []:
        name = entry.get("model_name")
        upstream = (entry.get("litellm_params") or {}).get("model", "")
        parts = upstream.split("/")
        if name and len(parts) >= 3:
            out[name] = "/".join(parts[1:])
        elif name and upstream:
            out[name] = upstream
    return out


def _proposal_named(conn, name: str) -> str:
    """The proposal whose name is `name`, ignoring case; "" if none."""
    row = conn.execute("SELECT name FROM proposals WHERE lower(name) = ? "
                       "ORDER BY id LIMIT 1",
                       ((name or "").lower(),)).fetchone()
    return row["name"] if row else ""


def _thing(conn, cand: dict, known: dict) -> str:
    """The proposal a candidates row runs, else what its alias serves, else its spec."""
    if cand.get("proposal"):
        return cand["proposal"]
    served = known.get(cand["spec"], "")
    if served:
        return _proposal_named(conn, served) or served
    return cand["spec"]


def _measured(conn, known: dict) -> dict[str, float]:
    """thing -> the earliest time a stored result row ran as it."""
    seen: dict[str, float] = {}
    for r in conn.execute(
            "SELECT c.spec, p.name AS proposal, MIN(r.generated_at) AS at "
            "FROM results x JOIN candidates c ON c.id = x.candidate_id "
            "JOIN runs r ON r.id = x.run_id "
            "LEFT JOIN proposals p ON p.id = c.proposal_id "
            "GROUP BY c.id, c.spec, p.name").fetchall():
        name = _thing(conn, dict(r), known).lower()
        at = r["at"]
        if name not in seen or (at is not None and (seen[name] is None
                                                    or at < seen[name])):
            seen[name] = at
    return seen


def unlinked(conn) -> dict[str, int]:
    """Receipt keys of result rows no candidates row claims, with row counts."""
    return {r["candidate"]: r["n"] for r in conn.execute(
        "SELECT candidate, COUNT(*) AS n FROM results "
        "WHERE candidate_id IS NULL GROUP BY candidate "
        "ORDER BY COUNT(*) DESC, candidate").fetchall()}


def adopted(conn, config=None) -> dict[str, set[str]]:
    """thing, lowercased -> how this project came to own it: served, measured, default."""
    from harness import candidates as C
    from harness import rank, screen, winners
    known = aliases(config)
    out: dict[str, set[str]] = {}
    for upstream in rank.serving(config):
        out.setdefault((_proposal_named(conn, upstream) or upstream).lower(),
                       set()).add("served")
    for name in _measured(conn, known):
        out.setdefault(name, set()).add("measured")
    for lane, name in winners.typed().items():
        spec = screen.candidate_for(lane, name, conn=conn) or name
        C.ensure(conn, spec, lane=lane)
        cand = C.get(conn, spec)
        thing = (_thing(conn, cand, known) if cand else spec).lower()
        out.setdefault(thing, set()).add("default")
    return out


def sightings(conn) -> list[dict]:
    """Every proposal with its first sighting and the sources that saw it."""
    q = """
        SELECT p.name AS name, MIN(s.seen_at) AS first_seen,
               GROUP_CONCAT(DISTINCT s.source) AS sources
        FROM proposals p JOIN sightings s ON s.proposal_id = p.id
        GROUP BY p.id
    """
    return [dict(r) for r in conn.execute(q)]


def report(conn, config=None) -> dict:
    """Which sources found what this project adopted, and what none of them did."""
    rows = {r["name"].lower(): r for r in sightings(conn)}
    first_run = _measured(conn, aliases(config))
    mine = adopted(conn, config)
    found, holes, late = [], [], []
    for name, how in sorted(mine.items()):
        row = rows.get(name)
        if row is None:
            holes.append({"name": name, "how": sorted(how)})
            continue
        sources = sorted({s for s in (row["sources"] or "").split(",")
                          if s and s not in NOT_DISCOVERY})
        entry = {"name": name, "how": sorted(how), "sources": sources,
                 "first_seen": row["first_seen"]}
        if not sources:
            # In the store, but only because a later tier put it there. That
            # is the store remembering our own work, not a source finding it.
            holes.append({**entry, "why": "only recorded by a tier of ours"})
            continue
        measured_at = first_run.get(name)
        if measured_at and row["first_seen"] > measured_at:
            entry["days_late"] = (row["first_seen"] - measured_at) / 86400.0
            late.append(entry)
        else:
            found.append(entry)
    by_source: dict[str, int] = {}
    for entry in found:
        for source in entry["sources"]:
            by_source[source] = by_source.get(source, 0) + 1
    proposed = {}
    for row in rows.values():
        for source in (row["sources"] or "").split(","):
            if source and source not in NOT_DISCOVERY:
                proposed[source] = proposed.get(source, 0) + 1
    return {"adopted": len(mine), "found": found, "late": late,
            "holes": holes, "unlinked": unlinked(conn),
            "by_source": dict(sorted(by_source.items(),
                                     key=lambda kv: -kv[1])),
            # WHAT THE SOURCES DID PRODUCE, beside what was adopted. Without
            # this a reader cannot tell a source that finds nothing from one
            # that finds plenty of things nobody has run yet -- and those want
            # opposite fixes.
            "proposed": dict(sorted(proposed.items(),
                                    key=lambda kv: -kv[1]))}
