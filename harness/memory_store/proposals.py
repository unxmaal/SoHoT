"""Proposals, sightings, verdicts and links: recording names and reading them back."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
import json
import time

# Patched names are read through the package, so one patch reaches every caller. #484.
from harness import memory_store as ms

from harness.memory_store.cards import with_lineage
from harness.memory_store.machines import remember_machine
from harness.memory_store.schema import (INSPECT, JUDGE, REGISTRIES, SCREEN, TERMINAL,
    VERDICTS)
from harness.memory_store.transitions import decide_or_skip


@dataclass
class Seen:
    """One proposal observed in one source at one time."""
    name: str
    source: str
    url: str = ""
    why: str = ""
    relevance: int = 0
    kind: str = "candidate"
    lane: str = ""
    resolved: str = ""
    #: One of REGISTRIES, or empty when the caller genuinely cannot say.
    registry: str = ""
    #: What the registry says this IS, as opposed to what one source said
    #: about it. Only filled by a tier that read the registry. Prose for the
    #: judge; the facts in it are columns written by set_card(). #414.
    description: str = ""
    #: What named `lane`: card, tag or prose. #414.
    lane_source: str = ""
    #: One of CATEGORIES, or "" when the caller cannot say. #576.
    category: str = ""


def record(conn: sqlite3.Connection, seen: Seen, at: float | None = None) -> int:
    """Upsert the proposal, add a sighting. Returns the proposal id.

    Seeing the same thing again is a SIGHTING, never a duplicate proposal:
    recurrence over time is the signal that separates a lasting thing from one
    that trended once.
    """
    now = time.time() if at is None else at
    cur = conn.execute("SELECT id FROM proposals WHERE name = ?", (seen.name,))
    row = cur.fetchone()
    if row:
        pid = row["id"]
        conn.execute(
            "UPDATE proposals SET last_seen = ?, "
            "  resolved = CASE WHEN ?<>'' THEN ? ELSE resolved END, "
            "  lane_source = CASE WHEN lane='' AND ?<>'' THEN ? "
            "                ELSE lane_source END, "
            "  lane = CASE WHEN lane='' THEN ? ELSE lane END, "
            "  registry = CASE WHEN registry='' THEN ? ELSE registry END, "
            "  description = CASE WHEN ?<>'' THEN ? ELSE description END, "
            "  category = CASE WHEN category='' THEN ? ELSE category END "
            "WHERE id = ?",
            (now, seen.resolved, seen.resolved, seen.lane, seen.lane_source,
             seen.lane, seen.registry,
             seen.description, seen.description, seen.category, pid))
    else:
        pid = conn.execute(
            "INSERT INTO proposals (name, kind, registry, lane, resolved, "
            "description, lane_source, category, first_seen, last_seen) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (seen.name, seen.kind, seen.registry, seen.lane, seen.resolved,
             seen.description, seen.lane_source if seen.lane else "",
             seen.category, now, now)).lastrowid
        # Weights downloaded before this proposal existed are now its. #429.
        conn.execute("UPDATE downloads SET proposal_id = ? WHERE "
                     "proposal_id IS NULL AND lower(repo) = ?",
                     (pid, seen.name.lower()))
    conn.execute(
        "INSERT OR IGNORE INTO sightings (proposal_id, source, url, why, "
        "relevance, seen_at, machine_id) VALUES (?,?,?,?,?,?,?)",
        (pid, seen.source, seen.url, seen.why, seen.relevance, now,
         remember_machine(conn)))
    conn.commit()
    return pid


def set_lane(conn, name: str, lane: str, source: str = "") -> bool:
    """Record a lane READ FROM THE REGISTRY, overwriting a guess.

    `record()` keeps the first non-empty lane, which is right for a value
    nothing can improve on. A lane is not that: the sweep can only guess from
    prose, and the inspect tier later reads the publisher's own task off the
    card. Without a way to correct it, the guess is permanent -- which is how
    four video models stayed in the image lane. #227.

    Returns whether anything changed, so a caller can say so.
    """
    from harness import lanes

    want = lanes.canonical(lane)
    if not want:
        return False
    row = conn.execute("SELECT id, lane FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row or lanes.canonical(row["lane"]) == want:
        return False
    conn.execute("UPDATE proposals SET lane = ?, lane_source = ? WHERE id = ?",
                 (want, source, row["id"]))
    return True


def set_size(conn: sqlite3.Connection, name: str, size_bytes: int) -> bool:
    """Record what inspect measured a candidate's weights at. 0 leaves a known size alone. #413."""
    if not size_bytes or int(size_bytes) <= 0:
        return False
    cur = conn.execute("UPDATE proposals SET size_bytes = ? WHERE name = ?",
                       (int(size_bytes), name))
    conn.commit()
    return cur.rowcount > 0


def link(conn: sqlite3.Connection, src: str, dst: str, relation: str,
         note: str = "", *, shared: int | None = None,
         crowd: int | None = None, score: float | None = None) -> None:
    """An edge between two proposals. Both must already exist.

    A neighbor score is columns, refreshed on every link; never prose. #416.
    """
    ids = {}
    for n in (src, dst):
        row = conn.execute("SELECT id FROM proposals WHERE name = ?",
                           (n,)).fetchone()
        if not row:
            raise KeyError(f"no proposal named {n!r}")
        ids[n] = row["id"]
    if score is None:
        conn.execute("INSERT OR IGNORE INTO edges (src, dst, relation, note) "
                     "VALUES (?,?,?,?)", (ids[src], ids[dst], relation, note))
    else:
        conn.execute(
            "INSERT INTO edges (src, dst, relation, note, shared, crowd, score) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT (src, dst, relation) DO UPDATE "
            "SET shared = excluded.shared, crowd = excluded.crowd, "
            "score = excluded.score",
            (ids[src], ids[dst], relation, note, shared, crowd, float(score)))
    conn.commit()


def settled(conn: sqlite3.Connection) -> set[str]:
    """Names in a terminal state, which must not be proposed again. #409."""
    q = (f"SELECT name FROM proposals WHERE state IN "
         f"({','.join('?' * len(TERMINAL))})")
    return {r["name"] for r in conn.execute(q, TERMINAL)}


def pending(conn, limit: int = 50, registry: str | None = None,
            screened: bool = True) -> list[str]:
    """Proposals nothing has answered yet, most-corroborated first.

    THE MISSING RUNG. The sweep writes proposals and every later tier read a
    different source -- inspect went to the crowd, so 233 swept proposals sat in
    the store with nothing consuming them. The ladder in #148 is sweep ->
    inspect -> judge -> screen -> measure, and without this the first arrow
    does not exist.

    Ordered by how many independent sightings a name has, because that is the
    project's own answer to a feed measuring popularity: a thing that keeps
    coming back is a different signal from a thing that trended once. Ties
    break on recency so a fresh proposal is not stuck behind an old one.

    A terminal verdict removes a name for good; `queued` and `screened` do not,
    because those are waypoints rather than answers.

    `registry` narrows to names one registry can answer for, and a caller that
    resolves names SHOULD pass it: the tier that clones from GitHub asked
    GitHub about HuggingFace model ids and 227 of 235 came back 404 (#167).

    None means every registry INCLUDING the unknown ones, which is right for a
    report and wrong for resolving. The EMPTY STRING asks for the unknown ones
    on their own -- names the store cannot route, which is work waiting on one
    question rather than work nobody can do.
    """
    where = "" if registry is None else "AND p.registry = ?"
    # Inspect must not re-answer a screened candidate: its `queued` sent it
    # back through the screen every loop. #393.
    stop = TERMINAL + (() if screened else ("screened",))
    args = (() if registry is None else (registry,)) + stop + (limit,)
    q = f"""
        SELECT p.name, COUNT(s.id) AS times, MAX(s.seen_at) AS last_seen
        FROM proposals p JOIN sightings s ON s.proposal_id = p.id
        WHERE p.resolved <> '' {where}
          AND p.state NOT IN ({','.join('?' * len(stop))})
        GROUP BY p.id
        ORDER BY times DESC, last_seen DESC
        LIMIT ?
    """
    return [r["name"] for r in conn.execute(q, args)]


def latest(conn, name: str) -> dict | None:
    """A name's state and the tier that set it, or None. #409."""
    row = conn.execute(
        "SELECT p.state AS outcome, v.tier FROM proposals p JOIN verdicts v "
        "ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()
    return dict(row) if row else None


def set_registry(conn, name: str, registry: str) -> None:
    """Record which registry answered for a name, once something has asked.

    The migration fills what the store already proves and stops there, so a
    name that arrived as prose keeps an empty registry: the sweep resolved it
    against a registry and did not write down which one. This is how that
    answer gets back in -- found by asking, not by guessing from the shape of
    the string.
    """
    if registry not in REGISTRIES:
        raise ValueError(f"{registry!r} is not one of {', '.join(REGISTRIES)}")
    conn.execute("UPDATE proposals SET registry = ? WHERE name = ?",
                 (registry, name))
    conn.commit()


def survivors(conn, limit: int = 10) -> list[dict]:
    """Candidates whose LATEST verdict is a passed screen, newest first.

    The latest verdict, not any verdict: a candidate that screened green and
    was later measured and declined must not be handed to the measure tier
    again every time the loop runs.
    """
    rows = conn.execute("""
        SELECT p.name, p.lane, p.attaches_to, v.detail
        FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id
        WHERE p.state = 'screened' AND v.tier = ?
        ORDER BY v.id DESC LIMIT ?
    """, (SCREEN, limit)).fetchall()
    return [dict(r) for r in rows]


def by_registry(conn) -> dict[str, int]:
    """How many unanswered proposals each registry owns, "" being the ones
    nothing can resolve. Reported rather than hidden: a name with no registry
    is work nobody can do, and it should be visible as that rather than as a
    404 from whichever tier guessed."""
    out = {}
    for r in conn.execute(
            "SELECT p.registry AS registry, COUNT(*) AS n FROM proposals p "
            "WHERE p.resolved <> '' AND p.state NOT IN "
            f"({','.join('?' * len(TERMINAL))}) GROUP BY p.registry", TERMINAL):
        out[r["registry"]] = r["n"]
    return out


def judgeable(conn, limit: int = 50) -> list[dict]:
    """What the inspect tier queued and no judge has scored, best-corroborated
    first, with everything judge.describe() is shown.

    THE SAME MISSING RUNG ONE TIER ALONG. _judge_fits() scores the Fit objects
    sitting in memory from the inspect run that produced them, so a judge can
    only ever see candidates inspected in the same process. Everything the
    store already holds is unreachable, and after #167 that is a queue of real
    candidates with real verdicts that nothing ranks.

    A proposal already scored by a judge is not returned. Re-scoring it would
    cost a model call to learn what is already recorded, and the rubric and
    judge model are recorded beside the score, so a run under a NEW rubric is
    told apart by that rather than by scoring everything again.
    """
    q = f"""
        SELECT p.name, p.lane, p.registry, p.kind, p.description,
               p.size_bytes, p.category,
               p.hf_task, p.library, p.card_tags, p.attaches_to, p.runtime_needed,
               p.model_type, p.remote_code,
               COUNT(s.id) AS times,
               MAX(CASE WHEN s.machine_id = ? THEN s.relevance END) AS relevance,
               MAX(s.seen_at) AS last_seen,
               MIN(s.source) AS source, MIN(s.why) AS why,
               (SELECT v.detail FROM verdicts v
                 WHERE v.proposal_id = p.id AND v.tier = ?
                 ORDER BY v.id DESC LIMIT 1) AS inspected
        FROM proposals p JOIN sightings s ON s.proposal_id = p.id
        WHERE p.id IN (
            SELECT proposal_id FROM verdicts
            WHERE tier = ? AND outcome = 'queued'
        ) AND p.id NOT IN (
            SELECT proposal_id FROM verdicts WHERE tier = ?
        )
        -- AND NOBODY HAS ALREADY ANSWERED IT. A terminal verdict from ANY
        -- tier means the question is settled, and this looked only at the
        -- judge: a candidate screened `broken` came straight back round, and
        -- three of the four adopt verdicts in the real store are one model
        -- measured, declined, and measured again. #253.
        --
        -- The STATE decides, which a retraction reopens; a screened name is
        -- past the judge, which may not move it back. #409.
        AND p.state NOT IN ({','.join('?' * (len(TERMINAL) + 1))})
        GROUP BY p.id
        ORDER BY times DESC, last_seen DESC
        LIMIT ?
    """
    return with_lineage(conn, [dict(r) for r in conn.execute(
        q, (ms.machine_row(conn), INSPECT, INSPECT, JUDGE, *TERMINAL,
            "screened", limit))])


def judgeable_total(conn) -> int:
    """How many candidates are waiting, whatever one run's budget is. A tier
    that takes the top 25 of a backlog and says nothing about the rest reads as
    finished."""
    return len(ms.judgeable(conn, limit=1_000_000))


def techniques(conn) -> list[dict]:
    """Every technique proposal not settled, with its evidence: title, link, sightings. #576."""
    from harness import papers
    from harness.memory_store.schema import TECHNIQUE
    # The paper's own sighting names it best; otherwise the newest that says anything.
    q = f"""
        SELECT p.name, p.lane, p.lane_source, p.description,
               COUNT(s.id) AS times, MAX(s.seen_at) AS last_seen,
               (SELECT s2.why FROM sightings s2 WHERE s2.proposal_id = p.id
                 AND s2.why <> '' ORDER BY (s2.source = ?) DESC, s2.seen_at DESC,
                 s2.id DESC LIMIT 1) AS title,
               (SELECT s3.url FROM sightings s3 WHERE s3.proposal_id = p.id
                 AND s3.url <> '' ORDER BY (s3.source = ?) DESC, s3.seen_at DESC,
                 s3.id DESC LIMIT 1) AS url
        FROM proposals p JOIN sightings s ON s.proposal_id = p.id
        WHERE p.category = ? AND p.state NOT IN ({','.join('?' * len(TERMINAL))})
        GROUP BY p.id
        ORDER BY times DESC, last_seen DESC, p.name
    """
    out = []
    for r in conn.execute(q, (papers.SOURCE, papers.SOURCE, TECHNIQUE, *TERMINAL)):
        row = dict(r)
        row["title"] = row["title"] or row["description"][:160] or row["name"]
        row["url"] = row["url"] or ""
        out.append(row)
    return out


def ranked(conn, limit: int = 50) -> list[dict]:
    """Everything a judge has scored, best first. What the tier is FOR."""
    q = """
        SELECT p.name, p.lane, v.score, v.rubric, v.judge, v.detail,
               v.decided_at
        FROM proposals p JOIN verdicts v ON v.proposal_id = p.id
        WHERE v.tier = ? AND v.score IS NOT NULL
        ORDER BY v.score DESC, v.id DESC
        LIMIT ?
    """
    return [dict(r) for r in conn.execute(q, (JUDGE, limit))]


def recurrence(conn: sqlite3.Connection, minimum: int = 2) -> list[dict]:
    """Proposals seen more than once, most-seen first.

    The answer to the README's own caveat that a feed measures popularity: a
    thing that keeps coming back over months is a different signal from a thing
    that trended once.
    """
    q = """
        SELECT p.name, p.kind, p.lane, p.resolved,
               COUNT(s.id) AS times, COUNT(DISTINCT s.source) AS sources,
               MIN(s.seen_at) AS first_seen, MAX(s.seen_at) AS last_seen
        FROM proposals p JOIN sightings s ON s.proposal_id = p.id
        -- COUNT repeated rather than `HAVING times >= ?`. SQLite lets HAVING
        -- see a select-list alias and standard SQL does not, so the alias
        -- version runs here and raises UndefinedColumn on Postgres. ORDER BY
        -- may use the alias in both, which is why it still does.
        GROUP BY p.id HAVING COUNT(s.id) >= ?
        ORDER BY times DESC, sources DESC, last_seen DESC
    """
    return [dict(r) for r in conn.execute(q, (minimum,))]


def precision(conn: sqlite3.Connection) -> dict:
    """How much of what the extractor proposes turns out to be worth anything.

    The number issue #49 asked for, as a query rather than a manual count.
    """
    total = conn.execute("SELECT COUNT(*) c FROM proposals").fetchone()["c"]
    resolved = conn.execute(
        "SELECT COUNT(*) c FROM proposals WHERE resolved <> ''").fetchone()["c"]
    counts = {o: 0 for o in VERDICTS}
    for r in conn.execute("SELECT outcome, COUNT(DISTINCT proposal_id) c "
                          "FROM verdicts GROUP BY outcome"):
        counts[r["outcome"]] = r["c"]
    judged = conn.execute("SELECT COUNT(DISTINCT proposal_id) c FROM verdicts "
                          "WHERE score IS NOT NULL").fetchone()["c"]
    return {"proposals": total, "resolved": resolved, "judged": judged,
            **{f"verdict_{k}": v for k, v in counts.items()}}


#: Why a name pulled out of prose did not become a proposal.
REJECTIONS = ("unresolvable", "not-a-repo", "duplicate", "already-measured",
              "below-relevance", "settled")


def reject(conn: sqlite3.Connection, name: str, source: str, reason: str,
           at: float | None = None) -> None:
    """Record a name that was extracted and thrown away.

    The thrown-away ones are the whole measurement. A store holding only what
    survived can report that 100% of proposals resolved, which is true and
    means nothing.
    """
    if reason not in REJECTIONS:
        raise ValueError(f"unknown rejection {reason!r}, known: "
                         f"{', '.join(REJECTIONS)}")
    conn.execute("INSERT OR IGNORE INTO extractions (name, source, reason, at) "
                 "VALUES (?,?,?,?)",
                 (name[:200], source, reason,
                  time.time() if at is None else at))
    conn.commit()


def extraction(conn: sqlite3.Connection) -> list[dict]:
    """Per source: how many extracted names survived, and why the rest did not.

    Issue #49 asked for extraction precision. This is the number.
    """
    kept = {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, COUNT(DISTINCT proposal_id) n FROM sightings "
        "GROUP BY source")}
    out = []
    for source in sorted(set(kept) | {r["source"] for r in conn.execute(
            "SELECT DISTINCT source FROM extractions")}):
        reasons = {r["reason"]: r["n"] for r in conn.execute(
            "SELECT reason, COUNT(*) n FROM extractions WHERE source=? "
            "GROUP BY reason", (source,))}
        dropped = sum(reasons.values())
        k = kept.get(source, 0)
        out.append({"source": source, "kept": k, "dropped": dropped,
                    "extracted": k + dropped,
                    "precision": (k / (k + dropped)) if (k + dropped) else 0.0,
                    "reasons": reasons})
    return sorted(out, key=lambda r: -r["extracted"])


def parents(conn: sqlite3.Connection, name: str,
            relation: str = "needs") -> list[str]:
    """Proposals with an edge INTO `name`. Which repos named this weight."""
    return [r["name"] for r in conn.execute(
        "SELECT src.name FROM edges e JOIN proposals src ON src.id = e.src "
        "JOIN proposals dst ON dst.id = e.dst "
        "WHERE dst.name = ? AND e.relation = ?", (name, relation))]


def retire_unlisted(conn: sqlite3.Connection, name: str, keep,
                    relation: str = "needs", why: str = "",
                    outcome: str = "ignored") -> list[str]:
    """Retire things `name` queued that it no longer ranks.

    A queue entry is a decision a ranking made at a point in time, and when the
    ranking changes every decision it made is suspect. Re-inspecting a repo used
    to only ADD, so the queue mixed picks from rules that no longer exist.

    A weight named by TWO repos is not this one's to retire: if any other parent
    still ranks it, it stays. Returns what was retired.
    """
    keep = set(keep)
    retired = []
    rows = conn.execute(
        "SELECT dst.name AS name FROM edges e JOIN proposals src ON src.id = e.src "
        "JOIN proposals dst ON dst.id = e.dst "
        "WHERE src.name = ? AND e.relation = ?", (name, relation)).fetchall()
    for row in rows:
        other = row["name"]
        if other in keep:
            continue
        cur = conn.execute("SELECT state FROM proposals WHERE name = ?",
                           (other,)).fetchone()
        if not cur or cur["state"] != "queued":
            continue
        if any(p != name for p in parents(conn, other, relation)):
            continue      # another repo still names it; not ours to retire
        # The state can move between the read above and this write.
        if decide_or_skip(conn, other, outcome, tier="inspect",
                          detail=why[:200], reason="candidate") is not None:
            retired.append(other)
    return retired


def by_source(conn: sqlite3.Connection) -> list[dict]:
    """Per source: how many it proposed, how many resolved, how many settled.

    Issue #49 asked for extraction precision and it was impossible to answer
    without a store. It is a query now, and it compares sources against each
    other rather than reporting one number for all of them.
    """
    return [dict(r) for r in conn.execute("""
        SELECT s.source AS source,
               COUNT(DISTINCT s.proposal_id) AS proposals,
               COUNT(DISTINCT CASE WHEN p.resolved <> '' THEN p.id END) AS resolved,
               COUNT(DISTINCT CASE WHEN p.state IN ('measured','declined',
                     'broken','ignored') THEN p.id END) AS settled,
               COUNT(DISTINCT CASE WHEN v.outcome = 'measured' THEN p.id END)
                     AS measured
        FROM sightings s
        JOIN proposals p ON p.id = s.proposal_id
        LEFT JOIN verdicts v ON v.proposal_id = p.id
        GROUP BY s.source ORDER BY proposals DESC""")]


def traverse(conn: sqlite3.Connection, name: str, depth: int = 2,
             direction: str = "both") -> list[dict]:
    """Walk the edge graph from `name`, forwards, backwards, or both.

    Recursive CTE rather than a graph engine: at this scale the graph is joins,
    and a server would buy traversal performance nothing here needs.
    """
    if direction not in ("forward", "backward", "both"):
        raise ValueError("direction must be forward, backward or both")
    row = conn.execute("SELECT id FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row:
        raise KeyError(f"no proposal named {name!r}")
    step = {"forward": "e.src = w.id",
            "backward": "e.dst = w.id",
            "both": "(e.src = w.id OR e.dst = w.id)"}[direction]
    other = {"forward": "e.dst",
             "backward": "e.src",
             "both": "CASE WHEN e.src = w.id THEN e.dst ELSE e.src END"}[direction]
    q = f"""
        WITH RECURSIVE walk(id, depth, relation) AS (
            -- CAST is load-bearing, not decoration. Postgres infers the
            -- parameter's type from the non-recursive term, decides smallint,
            -- and then refuses the recursive term where the column is integer:
            -- "column 1 has type smallint in the non-recursive term but type
            -- integer overall". SQLite accepts the cast and ignores it.
            SELECT CAST(? AS INTEGER), 0, ''
            UNION
            SELECT {other}, w.depth + 1, e.relation
            FROM edges e JOIN walk w ON {step}
            WHERE w.depth < ?
        )
        SELECT p.name, p.kind, p.lane, w.depth, w.relation
        FROM walk w JOIN proposals p ON p.id = w.id
        WHERE w.depth > 0
        ORDER BY w.depth, p.name
    """
    return [dict(r) for r in conn.execute(q, (row["id"], depth))]


def export(conn: sqlite3.Connection) -> str:
    """The whole store as JSON, for a human or another tool."""
    out = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
           for t in ("proposals", "sightings", "verdicts", "edges",
                     "human_votes")}
    return json.dumps(out, indent=2)
