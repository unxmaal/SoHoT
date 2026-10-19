"""When a settled verdict may be asked again: until-conditions and receipts that are gone."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import re

# Patched names are read through the package, so one patch reaches every caller. #484.
from harness import memory_store as ms

from harness.memory_store.machines import recorded_facts, remember_machine
from harness.memory_store.schema import INSPECT, SCREEN, TERMINAL, _columns
from harness.memory_store.transitions import retract


def dangling_receipts(conn: sqlite3.Connection, exists=None) -> list:
    """Verdicts citing a run that is no longer on disk.

    A VERDICT WHOSE EVIDENCE IS GONE CANNOT BE RE-JUDGED. Schema 10 exists
    because verdicts were recorded from runs that never reached a model, and
    the fix required reading those runs back -- which is impossible once the
    directory is deleted. That migration ran once; nothing has checked since,
    and 7 of the 55 verdicts that name a run already point at nothing.

    A RELATIVE PATH IS RESOLVED BEFORE IT IS CALLED MISSING. Six of the seven
    rows this first reported as gone are `runs/cycle-screen` and friends,
    which are relative to paths.home() and exist. Reading them against the
    process's cwd made a healthy store look half-rotten -- the same class of
    error as every defect this function exists to find, committed by the
    finder. The column holds both spellings because nothing ever normalised
    it; resolving here is what makes the answer true rather than tidy.

    `exists` is injected so this is testable without staging a filesystem.
    """
    exists = exists if exists is not None else (lambda p: Path(p).exists())
    rows = conn.execute(
        "SELECT v.id, v.outcome, v.tier, v.run_path, p.name "
        "FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
        "WHERE v.run_path != '' AND v.run_id IS NULL").fetchall()
    out = []
    for r in rows:
        if any(exists(c) for c in resolved_run_paths(r["run_path"])):
            continue
        out.append(dict(r))
    return out


def resolved_run_paths(run_path: str) -> list[str]:
    """Every place `run_path` could mean, most likely first.

    The column mixes absolute paths with paths relative to the project home,
    because nothing ever normalised it and both spellings were written by
    code that was correct from where it stood.
    """
    from harness import paths

    raw = (run_path or "").strip()
    if not raw:
        return []
    if Path(raw).is_absolute():
        return [raw]
    return [raw, str(paths.home() / raw)]


#: Every until key a writer may record, and the one quantity its reader compares. #928.
UNTIL = {
    "runtime": "a runtime this machine has (machines.runtimes)",
    "version": "the installed version of a package (machines.versions)",
    "memory_gb": "this machine's total RAM in GB (machines.memory_gb)",
    "ceiling_gb": "the largest weight this machine loads, GiB (inspect.ceiling_bytes)",
    "room_gb": "the memory guard's budget now with nothing resident (memory.room_gb)",
    "limit": "a limit this harness chose (reasons.limits)",
    "cases": "how many cases a lane has (holdout.for_lane)",
    "commit_after": "the upstream's last commit date (inspect.upstream_commit, per row)",
    "format": "a weight format a runner reads; fetching.format_waits reads it, not until_met",
    "layout": "a weight layout harness.variants groups; inspect re-reads it each sweep, not until_met",
    "runner": "an engine this harness registers (engines.names); none by that name exists yet",
    "policy": "a model type the pinned transformers ships natively (remote_code.native_types)",
    "package": "a distribution installed in a runner venv (runner_gaps.has_package)",
}


def until_met(until: str, facts: dict | None = None) -> bool:
    """Whether `facts` satisfies the condition a verdict is waiting on.

    A PREDICATE, NOT A SENTENCE. The whole point of #266 is that a machine
    fact buried in prose cannot be queried, so writing the condition as prose
    would move the defect rather than fix it.

    The forms and the one quantity each reads are UNTIL.

    THE FIRST THREE ARE ABOUT THE MACHINE AND THE FOURTH IS NOT, which is why
    `facts` is a plain dict rather than a Machine: a verdict waits on whatever
    would change it, and `dead` waits on somebody else's repository.
    An unrecognised condition is NOT met, so a typo leaves the verdict
    standing rather than silently re-queueing everything.
    """
    if not until:
        return False
    facts = facts if facts is not None else ms.this_machine()
    key, _, want = until.partition(":")
    if key == "runtime":
        have = (facts.get("runtimes") or "").split(",")
        return any(rt in have for rt in want.split("|"))
    if key in ("memory_gb", "ceiling_gb") and want.startswith(">"):
        try:
            return float(facts.get(key) or 0) > float(want[1:])
        except ValueError:
            return False
    if key == "room_gb" and want.startswith(">"):
        if "room_gb" in facts:
            have = facts.get("room_gb")
        else:
            from harness import memory
            have = memory.room_gb()
        try:
            return have is not None and float(have) > float(want[1:])
        except ValueError:
            return False
    if key == "version" and ">" in want:
        pkg, _, floor = want.partition(">")
        # The recorded versions, the same probe load_until wrote from. #389, #415.
        have = (facts.get("versions") or {}).get(pkg)
        a, b = _version_tuple(have), _version_tuple(floor)
        return a is not None and b is not None and a > b
    if key == "limit" and ">" in want:
        # A limit this harness chose; met once the harness chooses more. #406.
        name, _, floor = want.partition(">")
        if "limits" in facts:
            have = (facts.get("limits") or {}).get(name)
        else:
            from harness import reasons
            have = reasons.limits().get(name)
        try:
            return have is not None and float(have) > float(floor)
        except ValueError:
            return False
    if key == "cases" and ">" in want:
        # A lane with too few cases to screen at the chosen confidence; met once it has more. #691.
        lane, _, floor = want.partition(">")
        if "cases" in facts:
            have = (facts.get("cases") or {}).get(lane)
        else:
            from harness import holdout
            split = holdout.for_lane(lane)
            have = len(set(split.dev) | set(split.holdout))
        try:
            return have is not None and int(have) > int(floor)
        except ValueError:
            return False
    if key == "runner":
        have = facts.get("engines")
        if have is None:
            from harness import engines
            have = engines.names()
        return bool(want) and want in have
    if key == "policy":
        # A repo's own code is never run; it loads once the pinned transformers ships its type. #950.
        rule, _, mtype = want.partition("@")
        if rule != "trust_remote_code" or not mtype:
            return False
        native = facts.get("native_types")
        if native is None:
            from harness import remote_code
            native = remote_code.native_types()[1]
        return mtype in native
    if key == "package":
        # A package a runner's venv lacked; met once that venv has it. #1008.
        dist, _, venv = want.partition("@")
        if not dist:
            return False
        have = facts.get("packages")
        if have is not None:
            return dist in (have.get(venv) or ())
        from harness import runner_gaps
        if venv in runner_gaps.GROUP_VENVS:
            # uv builds a group's venv when a run first needs it, so the deploy declaring it ends the wait. #1024.
            return runner_gaps.provides(dist, venv)
        return runner_gaps.has_package(dist, venv)
    if key == "commit_after":
        seen = (facts.get("last_commit") or "").strip()
        # STRING COMPARISON IS CORRECT FOR ISO-8601 AND ONLY FOR IT, so both
        # sides are checked for the shape first. A length test was not enough
        # and the negative control caught it: "last Tuesday" is twelve
        # characters and sorts ABOVE any date beginning with a digit, so an
        # unparseable field reopened the verdict -- the opposite of the safe
        # direction this function is supposed to fail in.
        if not (_ISO_DATE.match(seen) and _ISO_DATE.match(want)):
            return False
        a, b = _instant(seen), _instant(want)
        # Instants, so `07.000Z` equals `07Z` and an offset is not compared as text. #961.
        return a > b if a is not None and b is not None else seen > want
    return False


def _instant(iso: str):
    """An ISO-8601 time as an aware datetime, UTC when it names no zone, or None."""
    from datetime import datetime, timezone
    try:
        got = datetime.fromisoformat(iso.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=timezone.utc)


def _version_tuple(v) -> tuple | None:
    """`0.31.10` as (0, 31, 10), so it sorts after `0.31.9`. None if unparseable."""
    parts = str(v or "").split(".")
    return tuple(int(x) for x in parts) if all(x.isdigit() for x in parts) else None


def revisitable(conn: sqlite3.Connection, facts: dict | None = None) -> list:
    """Verdicts decided elsewhere whose condition THIS machine now satisfies.

    The read path the columns exist for. A candidate declined on a machine
    with no cuda is not declined on the box with the card, and until now
    nothing could find those rows: the reason was a sentence.

    Only the verdict holding the state counts, so a condition that was
    already retracted does not resurrect.
    """
    if facts is None:
        # What this machine recorded, versions included, not a second probe. #415.
        facts = recorded_facts(conn, remember_machine(conn)) or ms.this_machine()
    rows = conn.execute("""
        SELECT p.name, p.lane, v.outcome, v.detail, v.until, v.tier,
               m.fingerprint AS decided_on
          FROM proposals p
          JOIN verdicts v ON v.id = p.state_verdict_id
          LEFT JOIN machines m ON m.id = v.machine_id
         WHERE v.until != ''
    """).fetchall()
    # Wherever it was decided: a refusal is written because its condition is
    # unmet, so meeting it later means the machine changed. #295.
    return [dict(r) for r in rows
            if r["outcome"] in TERMINAL and until_met(r["until"], facts)]


def requeue_revisitable(conn, facts: dict | None = None) -> list[str]:
    """Retract every revisitable verdict back to the inspect tier. #295."""
    names = []
    for r in revisitable(conn, facts):
        retract(conn, r["name"], f"{r['until']} is met here")
        names.append(r["name"])
    conn.commit()
    return names


def waiting_on_upstream(conn) -> list[dict]:
    """State-holding refusals whose until is commit_after:<iso>, with the repo and registry to ask. #961."""
    rows = conn.execute(
        "SELECT p.name, COALESCE(NULLIF(p.resolved, ''), p.name) AS repo, p.registry, v.until "
        "FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        f"WHERE v.until LIKE 'commit_after:%' AND v.outcome IN ({','.join('?' * len(TERMINAL))}) "
        "ORDER BY p.name", tuple(TERMINAL)).fetchall()
    return [dict(r) for r in rows]


def upstream_committed(conn, last_commit) -> dict:
    """Ask each commit_after row's upstream; last_commit(repo, registry) gives an ISO time, '' unknown, None to stop. #961."""
    got = {"waiting": 0, "asked": 0, "answered": 0, "committed": []}
    rows = waiting_on_upstream(conn)
    got["waiting"] = len(rows)
    for r in rows:
        seen = last_commit(r["repo"], r["registry"])
        if seen is None:
            break
        got["asked"] += 1
        if not seen:
            continue
        got["answered"] += 1
        if until_met(r["until"], {"last_commit": seen}):
            got["committed"].append({**r, "last_commit": seen})
    return got


def requeue_upstream_committed(conn, last_commit) -> dict:
    """Retract to inspect each commit_after refusal whose upstream has committed since. #961."""
    got = upstream_committed(conn, last_commit)
    for r in got["committed"]:
        retract(conn, r["name"], f"{r['until']} is met: the upstream last committed {r['last_commit']}")
    conn.commit()
    return got


#: A recorded ceiling this far under the current one is a different machine's answer. #880.
STALE_CEILING_GB = 1.0


def stale_too_big(conn, ceiling_gb: float) -> list[dict]:
    """Too-big inspect refusals judged against a ceiling below `ceiling_gb`, whose size this ceiling re-asks. #880."""
    from harness import reasons
    if "ceiling_gb" not in _columns(conn, "verdicts"):
        return []
    rows = conn.execute("""
        SELECT p.name, v.ceiling_gb, v.size_bytes, v.until, v.decided_at
          FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id
         WHERE p.state = 'declined' AND v.tier = ? AND v.reason = ?
           AND v.until LIKE 'ceiling_gb:>%' AND v.ceiling_gb IS NOT NULL
           AND v.ceiling_gb + ? < ?
         ORDER BY p.name
    """, (INSPECT, reasons.MACHINE, STALE_CEILING_GB, float(ceiling_gb or 0))).fetchall()
    return [dict(r) for r in rows]


def requeue_stale_too_big(conn, ceiling_gb: float | None = None) -> list[str]:
    """Hand each stale too-big refusal back to inspect, which re-sizes it with current code. #880."""
    here = ms.this_machine()["ceiling_gb"] if ceiling_gb is None else ceiling_gb
    names = []
    for r in stale_too_big(conn, here):
        retract(conn, r["name"], f"too-big against a {r['ceiling_gb']:g} GiB ceiling; "
                                 f"re-inspected against {here:g} GiB")
        names.append(r["name"])
    conn.commit()
    return names


def unranked_terminal(conn) -> list[dict]:
    """Proposals held terminal by a parent's ranking, which says nothing about them. #954."""
    from harness.memory_store.proposals import UNRANKED
    return [dict(r) for r in conn.execute(
        "SELECT p.name, v.id AS verdict_id, v.decided_at FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        f"WHERE p.state IN ({','.join('?' * len(TERMINAL))}) AND v.tier = ? AND v.detail = ? ORDER BY p.name",
        (*TERMINAL, INSPECT, UNRANKED))]


def requeue_unranked(conn) -> list[str]:
    """Hand back to inspect each weight a parent's ranking retired before #954."""
    names = [r["name"] for r in unranked_terminal(conn)]
    for name in names:
        retract(conn, name, "a parent's download ranking retired it; inspect reads it on its own")
    conn.commit()
    return names


def sized_by_repo_total(conn) -> list[dict]:
    """State-holding too-big HF inspect refusals whose detail names no variant: sized by the listing's sum. #947."""
    from harness import reasons, variants
    rows = conn.execute("""
        SELECT p.name, v.decided_at, v.detail
          FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id
         WHERE p.state = 'declined' AND v.tier = ? AND v.reason = ? AND p.registry = ?
           AND v.detail LIKE 'too-big:%' AND v.detail NOT LIKE ? AND v.detail NOT LIKE '%GiB resident%'
         ORDER BY p.name
    """, (INSPECT, reasons.MACHINE, ms.HUGGINGFACE, f"too-big: {variants.MARK}%")).fetchall()
    return [dict(r) for r in rows]


def runtime_by_library(conn) -> list[dict]:
    """State-holding needs-vllm fetch refusals whose last inspect read no variant: the library tag decided. #947."""
    from harness import reasons, variants
    rows = conn.execute("""
        SELECT p.name, v.decided_at, v.detail
          FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id
         WHERE p.state = 'declined' AND v.tier = 'fetch' AND v.reason = ? AND p.registry = ?
           AND v.until = 'runtime:vllm'
           AND COALESCE((SELECT vi.detail FROM verdicts vi
                          WHERE vi.proposal_id = p.id AND vi.tier = ? AND vi.reason != ?
                          ORDER BY vi.id DESC LIMIT 1), '') NOT LIKE ?
         ORDER BY p.name
    """, (reasons.MACHINE, ms.HUGGINGFACE, INSPECT, reasons.REOPENED,
          f"%{variants.MARK}%")).fetchall()
    return [dict(r) for r in rows]


def requeue_old_sizing(conn) -> list[str]:
    """Hand back to inspect each refusal sized by the repo total or refused on the library tag. #947."""
    names = []
    for r in sized_by_repo_total(conn):
        retract(conn, r["name"], "too-big on the listing's sum; re-inspected by its smallest variant")
        names.append(r["name"])
    for r in runtime_by_library(conn):
        retract(conn, r["name"], "needs-vllm on the library tag; re-inspected by its variants")
        names.append(r["name"])
    conn.commit()
    return names


def requeue_missing_in_snapshot(conn) -> list[str]:
    """Send back to screen each BROKEN screen whose loader missed a file in our own snapshot. #911."""
    from harness import reasons
    rows = conn.execute(
        "SELECT p.name, v.detail FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        "WHERE p.state = 'broken' AND v.tier = ? ORDER BY p.name", (SCREEN,)).fetchall()
    names = [r["name"] for r in rows if reasons.in_our_snapshot(r["detail"])]
    for name in names:
        retract(conn, name, "a loader missed a file in our own snapshot; the harness's routing, "
                            f"not a verdict on {name}", tier=SCREEN)
    conn.commit()
    return names


#: Until keys a screen runtime decline may hold; before #950 every one was `version`.
GAP_KEYS = ("version", "runner", "format", "policy", "package")
#: The ones a runner gap waits on, for the runners-wanted report.
RUNNER_WAITS = ("runner", "format", "policy", "package")


def _runtime_declines(conn) -> list:
    return conn.execute(
        "SELECT p.name, p.lane, p.hf_task, p.library, p.card_tags, p.model_type, p.remote_code, "
        "v.id, v.until, v.detail, v.failure_class, v.decided_at, coalesce(c.spec, '') AS spec "
        "FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        "LEFT JOIN candidates c ON c.id = v.candidate_id "
        "WHERE p.state = 'declined' AND v.tier = ? AND v.reason = 'runtime' ORDER BY v.id",
        (SCREEN,)).fetchall()


def _screen_class(row) -> str:
    """A screen runtime decline's class: its column, else the sentence screen._sentence wrote. #292."""
    from harness import reasons
    if row["failure_class"] in (reasons.LOAD_FAILED_RUNTIME, reasons.LOAD_FAILED_LAYOUT):
        return row["failure_class"]
    low = (row["detail"] or "").lower()
    if low.startswith("needs its own runner"):
        return reasons.LOAD_FAILED_LAYOUT
    if low.startswith("the installed runtime could not load it"):
        return reasons.LOAD_FAILED_RUNTIME
    return ""


def runner_gap_rewrites(conn) -> list[dict]:
    """Screen runtime declines whose until is not the one their recorded detail and card name now. #950."""
    from harness import runner_gaps
    from harness.serving import LLAMACPP_PREFIX
    out = []
    for r in _runtime_declines(conn):
        until = r["until"] or ""
        # llama-server's load failures are #953's.
        if until.partition(":")[0] not in GAP_KEYS or until.startswith("version:llama.cpp") \
                or r["spec"].startswith(LLAMACPP_PREFIX):
            continue
        cls = _screen_class(r)
        new = runner_gaps.cause_until(cls, r["detail"], r["spec"] or r["name"], dict(r)) if cls else ""
        if new and new != until:
            out.append({"id": r["id"], "name": r["name"], "until": until, "new": new, "class": cls,
                        "decided_at": r["decided_at"]})
    return out


def rewrite_runner_gap_untils(conn) -> list[str]:
    """Give each runner_gap_rewrites row its new until and class, in place; the caller commits. #950."""
    names = []
    for r in runner_gap_rewrites(conn):
        conn.execute("UPDATE verdicts SET until = ?, failure_class = ? WHERE id = ?",
                     (r["new"], r["class"], r["id"]))
        names.append(r["name"])
    return names


def cards_to_reread(conn) -> list[str]:
    """Screen runtime declines with no model_type and no inspect since, so their card cannot tell the gap. #950."""
    rows = conn.execute(
        "SELECT p.name FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        "WHERE p.state = 'declined' AND v.tier = ? AND v.reason = 'runtime' "
        "AND coalesce(p.model_type, '') = '' AND coalesce(p.registry, '') IN ('', ?) "
        "AND NOT EXISTS (SELECT 1 FROM sightings s WHERE s.proposal_id = p.id "
        "  AND s.source = 'inspect' AND s.seen_at > v.decided_at) ORDER BY p.name",
        (SCREEN, ms.HUGGINGFACE)).fetchall()
    return [r["name"] for r in rows]


def runner_waits(conn, lane: str = "") -> list[dict]:
    """Screen declines waiting on a runner, format or policy this harness lacks, for runners wanted. #950."""
    from harness import lanes
    out = []
    for r in _runtime_declines(conn):
        if (r["until"] or "").partition(":")[0] in RUNNER_WAITS and (
                not lane or lanes.serves(r["lane"] or "", lane)):
            out.append({"name": r["name"], "lane": r["lane"],
                        "why_not": f"waits on {r['until']}: {(r['detail'] or '')[:200]}"})
    return out


_NONE_OF = re.compile(r"none of ([\w, ]+)$")


_TOO_BIG = re.compile(r"^too-big:.*?([\d.]+)\s*GiB")


def until_for(detail: str) -> str:
    """The predicate a refusal's own sentence implies, or '' if none."""
    detail = detail or ""
    m = _TOO_BIG.match(detail)
    if m:
        return f"ceiling_gb:>{float(m.group(1)):.1f}"
    for phrase, until in _UNTIL_FROM_DETAIL:
        if detail.lower().startswith(phrase):
            many = _NONE_OF.search(detail)
            if many:
                return "runtime:" + "|".join(
                    rt.strip() for rt in many.group(1).split(","))
            return until
    return ""


#: What a pre-#266 refusal was waiting for, derived from the phrase the tier
#: wrote. Keyed on the runtime name because machine.refuses() builds these,
#: so the two stay in step without a second list to maintain.
_UNTIL_FROM_DETAIL = tuple(
    (f"needs-{rt}", f"runtime:{rt}")
    for rt in ("cuda", "rocm", "vllm", "mlx", "llamacpp"))


#: A date this can order by comparing strings. Anything else is not met.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


#: The fetch decline an attachment word wrote; its proposal is held by that word.
ATTACHMENT_DECLINE = "attaches to a model rather than being one"


def stale_attachments(conn, every: bool = False) -> list[dict]:
    """HF proposals whose attaches_to an older rule set: a description backfill, or a word its tags no longer give. #949."""
    from harness import screen
    from harness.memory_store.schema import HUGGINGFACE
    rows = conn.execute("SELECT p.name, p.attaches_to, p.card_read, p.card_tags, p.state, v.detail, "
                        "COALESCE(v.decided_at, p.first_seen) AS decided_at "
                        "FROM proposals p LEFT JOIN verdicts v ON v.id = p.state_verdict_id "
                        "WHERE p.attaches_to != '' AND p.registry = ? ORDER BY p.name",
                        (HUGGINGFACE,)).fetchall()
    out = []
    for r in rows:
        try:
            tags = json.loads(r["card_tags"] or "[]")
        except ValueError:
            tags = []
        if every or r["card_read"] != "card" or not screen.tags_support(r["attaches_to"], tags):
            out.append(dict(r))
    return out


def rederive_attachments(conn, read=None, every: bool = False) -> dict:
    """Re-read each stale attachment's card under the current rule; requeue a decline it no longer holds. #949."""
    from harness import inspect as ins
    read = read or ins.hf_model
    got = {"read": 0, "changed": [], "requeued": [], "unread": [], "gone": []}
    for r in stale_attachments(conn, every=every):
        try:
            card = ins.card_facts(read(r["name"]))
        except ins.InspectError as exc:
            got["gone" if isinstance(exc, ins.Gone) else "unread"].append(f"{r['name']}: {exc}")
            continue
        got["read"] += 1
        ms.set_card(conn, r["name"], card)
        if card.attaches_to == r["attaches_to"]:
            continue
        got["changed"].append({"name": r["name"], "was": r["attaches_to"], "now": card.attaches_to})
        if not card.attaches_to and r["state"] == "declined" and ATTACHMENT_DECLINE in (r["detail"] or ""):
            retract(conn, r["name"], f"{r['attaches_to']} was an older rule's reading of its card; "
                                     f"its tags and listing say it is a model (#949)")
            got["requeued"].append(r["name"])
    conn.commit()
    return got
