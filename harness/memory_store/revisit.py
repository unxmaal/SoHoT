"""When a settled verdict may be asked again: until-conditions and receipts that are gone."""
from __future__ import annotations

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
    "commit_after": "the upstream's last commit date (facts.last_commit)",
    "format": "a weight format a runner reads; fetching.format_waits reads it, not until_met",
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
    if key == "commit_after":
        seen = (facts.get("last_commit") or "").strip()
        # STRING COMPARISON IS CORRECT FOR ISO-8601 AND ONLY FOR IT, so both
        # sides are checked for the shape first. A length test was not enough
        # and the negative control caught it: "last Tuesday" is twelve
        # characters and sorts ABOVE any date beginning with a digit, so an
        # unparseable field reopened the verdict -- the opposite of the safe
        # direction this function is supposed to fail in.
        return bool(_ISO_DATE.match(seen) and _ISO_DATE.match(want)
                    and seen > want)
    return False


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
