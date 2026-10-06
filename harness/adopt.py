"""The loop's closing step: a measured winner becomes the lane's default.

Without this the loop cannot change anything. A candidate can be swept,
inspected, ranked, fetched, screened, measured, beat the incumbent on the
lane's own metric, and the lane goes on serving the constant somebody typed
into a source file. `lh discover --winners` reported that disagreement and
stopped, which makes the gap visible and closes none of it.

WHAT ADOPTION IS NOT. It is not "the challenger scored higher". A run is a
sample, and this project has twice drawn a conclusion from a difference that
was not there: the crowd decay called inert on statistics blind to ordering,
and a temperature trend of 12/27 to 9/27 that is 5 lost against 2 gained,
p=0.45. So a challenger must beat the incumbent on the LANE'S OWN METRIC and
the cell-by-cell comparison must be significant. Anything less is recorded as
a loss, which is the more useful row: it stops the same candidate being
re-proposed every sweep.

THE ADOPTED WINNER IS A STORE FACT, not an edit to a source file. A loop that
rewrites constants would need a commit to take effect and could not be undone
without another one. The lane reads the record and falls back to the typed
constant when nothing has been adopted, so a fresh checkout behaves exactly as
it does today.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The tier that records an adoption. See memory_store.TIERS.
TIER = "adopt"

#: How an adoption was decided. A MEASURED win is a fact about the hardware
#: that ran it and serves only there; a person's preference for a config is
#: not, and serves on every machine. #412.
MEASURED, BY_HAND = "measured", "by-hand"
HOW = (MEASURED, BY_HAND)

#: Below this the difference is not established and the incumbent stays. The
#: exact McNemar test on discordant cells; see harness/paired.py.
ALPHA = 0.05


@dataclass(frozen=True)
class Verdict:
    lane: str
    incumbent: str
    challenger: str
    adopt: bool
    why: str
    how: str = MEASURED


def better(incumbent: dict, challenger: dict) -> bool:
    """Is the challenger's summary row better on the lane's own metric?

    Delegates to winners.order_key so there is one ordering rule in the
    project rather than two that can disagree. RULE #254.
    """
    from harness import winners

    return winners.order_key(challenger) > winners.order_key(incumbent)


def decide_by_hand(lane: str, incumbent: str, challenger: str,
                   pairs: list[dict]) -> Verdict:
    """The same closing step for a lane no program can score. Issue #279.

    The two statistical gates are replaced by ONE question a person already
    answered, because for these lanes the gates cannot be computed: there is
    no per-clip style-similarity metric, and a lane's own checkers are blind
    to the thing being compared. `music` scored 4/4 with identical duration
    adherence for both candidates while a person picked different winners in
    different cases -- information the programmatic path structurally could
    not produce.

    UNJUDGED IS NOT A LOSS. `better()` returning False means the challenger
    was measured and came up short; an unjudged lane has not been asked. The
    first is terminal, the second must stay queued, and conflating them
    settles a candidate nobody looked at.
    """
    from harness import human

    won, why = human.lane_verdict(lane, pairs)
    if won is None:
        return Verdict(lane, incumbent, challenger, False, f"not judged: {why}",
                       BY_HAND)
    if not won:
        return Verdict(lane, incumbent, challenger, False,
                       f"the incumbent stays: {why}", BY_HAND)
    if won != challenger:
        return Verdict(lane, incumbent, challenger, False,
                       f"the incumbent was preferred: {why}", BY_HAND)
    return Verdict(lane, incumbent, challenger, True,
                   f"preferred by hand: {why}", BY_HAND)


def decide(lane: str, incumbent: dict, challenger: dict,
           rows: list[dict] | None = None) -> Verdict:
    """Whether this challenger replaces this incumbent.

    Two gates, both required. The metric gate answers "better on what this lane
    is about". The paired gate answers "by more than the noise". A challenger
    that passes one and not the other is a loss.
    """
    from harness import paired

    name_i = incumbent.get("candidate", "")
    name_c = challenger.get("candidate", "")
    if not better(incumbent, challenger):
        return Verdict(lane, name_i, name_c, False,
                       "does not beat the incumbent on the lane's metric")
    if not rows:
        return Verdict(lane, name_i, name_c, False,
                       "no paired rows, so the difference is unmeasured")
    cell = paired.head_to_head(rows, name_i, name_c)
    if not cell.discordant and not cell.unchanged:
        return Verdict(lane, name_i, name_c, False,
                       f"{name_i} and {name_c} share no case in this run, so "
                       f"there is nothing to compare")
    if cell.p > ALPHA:
        return Verdict(lane, name_i, name_c, False,
                       f"better on the metric, but {cell.lost} lost against "
                       f"{cell.gained} gained is p={cell.p:.2f}, so the "
                       f"difference is not established")
    return Verdict(lane, name_i, name_c, True,
                   f"beats {name_i} on the lane's metric, {cell.gained} gained "
                   f"against {cell.lost} lost, p={cell.p:.2f}")


#: Candidates that exist to measure local models against. #374.
REFERENCE_PREFIXES = ("claude-code:", "cloud-")


def is_reference(candidate: str) -> bool:
    return (candidate or "").startswith(REFERENCE_PREFIXES)


def record(conn, verdict: Verdict, spec: str = "",
           run_id: int | None = None) -> int:
    """Write an adoption, or the loss, on the candidate that ran. #407, #412.

    `spec` is what ran; `verdict.challenger` is used when it is one. The
    verdict lands on the candidate's proposal, or on the candidate alone for
    a typed default or a command-line spec, and never creates a proposal. An
    adoption is also an `adoptions` row, which is what every reader asks.
    """
    from harness import candidates
    from harness import memory_store as ms

    if is_reference(verdict.challenger) or is_reference(spec):
        verdict = Verdict(verdict.lane, verdict.incumbent, verdict.challenger,
                          False, f"reference model; never a lane default "
                          f"({verdict.why})", verdict.how)
    outcome = "measured" if verdict.adopt else "declined"
    detail = f"{verdict.lane}: {verdict.why}"
    spec = spec or verdict.challenger
    # A text-lane spec is the proposal's own name; anything else maps by row.
    cid = candidates.ensure(conn, spec, proposal=spec, lane=verdict.lane)
    if cid is None:
        raise ValueError(f"{spec!r} is not a spec any runner takes, so an "
                         f"adoption of it could never be served")
    row = candidates.get(conn, spec)
    vid = ms.decide(conn, row["proposal"] or "", outcome, tier=TIER,
                    detail=detail[:200], candidate_id=cid, run_id=run_id,
                    reason="candidate")
    if verdict.adopt:
        if verdict.how not in HOW:
            raise ValueError(f"unknown adoption kind {verdict.how!r}")
        mid = conn.execute("SELECT machine_id FROM verdicts WHERE id = ?",
                           (vid,)).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO adoptions (lane, candidate_id, incumbent_id, "
            "run_id, verdict_id, machine_id, how, adopted_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (verdict.lane.strip().lower(), cid,
             _incumbent_id(conn, verdict.lane, verdict.incumbent), run_id, vid,
             mid["machine_id"] if mid else None, verdict.how, _now()))
        conn.commit()
    return vid


def _now() -> float:
    import time
    return time.time()


def _incumbent_id(conn, lane: str, name: str) -> int | None:
    """The candidates row of what the lane served before, if it can be named."""
    from harness import candidates
    if not name:
        return None
    got = candidates.get(conn, name)
    if got:
        return got["id"]
    try:
        from harness import screen
        return candidates.ensure(
            conn, screen.candidate_for(lane, name) or name,
            lane=lane)
    except Exception:  # noqa: BLE001
        return None


#: Read the adoptions this machine serves; see here().
HERE = object()


def here(conn) -> tuple[int, ...]:
    """This machine's id, as runs.here() finds it by fingerprint. #356, #415."""
    from harness import runs
    try:
        return tuple(runs.here(conn))
    except Exception:  # noqa: BLE001
        return ()


def current(conn, machine=HERE) -> dict[str, dict]:
    """lane -> the adoption row a machine serves, with its spec.

    The newest adoption for the lane that was measured on that machine or
    decided by hand anywhere. One no machine is recorded for serves
    everywhere, as every adoption did before #412. `machine` is HERE, a machine id, or a tuple of
    ids. A reference model is never a lane default. #374, #412.
    """
    ids = here(conn) if machine is HERE else (
        tuple(machine) if isinstance(machine, (tuple, list, set))
        else (() if machine is None else (machine,)))
    marks = ",".join("?" * len(ids)) or "NULL"
    rows = conn.execute(
        "SELECT a.*, c.spec FROM adoptions a "
        "JOIN candidates c ON c.id = a.candidate_id "
        f"WHERE a.how = ? OR a.machine_id IS NULL "
        f"OR a.machine_id IN ({marks}) "
        "ORDER BY a.adopted_at, a.id", (BY_HAND, *ids)).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        if not is_reference(row["spec"]):
            out[row["lane"]] = dict(row)
    return out


def everywhere(conn) -> dict[str, set[str]]:
    """lane -> every spec some machine in the store serves by adoption."""
    out: dict[str, set[str]] = {}
    mids = [r["machine_id"] for r in conn.execute(
        "SELECT DISTINCT machine_id FROM adoptions").fetchall()]
    for mid in mids:
        for lane, row in current(conn, mid).items():
            out.setdefault(lane, set()).add(row["spec"])
    return out


def adopted(conn, machine=HERE) -> dict[str, str]:
    """The lane -> spec this machine serves by adoption."""
    return {lane: row["spec"] for lane, row in current(conn, machine).items()}


def lane_defaults(conn=None, machine=HERE, typed=None) -> dict[str, str]:
    """What every lane serves now: its adoption here, else the typed default.

    Never raises: a missing, locked or older store leaves the typed defaults.
    """
    if typed is None:
        from harness import winners
        typed = winners.typed()
    close = conn is None
    try:
        if conn is None:
            from harness import memory_store as ms
            conn = ms.connect()
        got = adopted(conn, machine)
    except Exception:  # noqa: BLE001
        got = {}
    finally:
        if close and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    return {**dict(typed), **got}


def default_for(lane: str, fallback: str, conn=None, machine=HERE) -> str:
    """What this lane serves right now: the adopted winner, else the constant.

    RESOLVED AT CALL TIME. `DEFAULT_TTS_MODEL` reaches its callers as a default
    ARGUMENT, captured when the function is defined, so rebinding the constant
    changes nothing -- the same trap that made SpeechRunner's declared voice
    unreachable (#195). An adoption that cannot take effect without a restart
    is a report with extra steps.

    Never raises and never blocks a generation. A store that is missing,
    locked or older than this code leaves the lane on its typed constant, which
    is what a fresh checkout does anyway.
    """
    if not lane:
        return fallback
    key = lane.strip().lower()
    return lane_defaults(conn, machine, typed={key: fallback}).get(key) \
        or fallback
