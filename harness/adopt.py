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
        return Verdict(lane, incumbent, challenger, False, f"not judged: {why}")
    if not won:
        return Verdict(lane, incumbent, challenger, False,
                       f"the incumbent stays: {why}")
    if won != challenger:
        return Verdict(lane, incumbent, challenger, False,
                       f"the incumbent was preferred: {why}")
    return Verdict(lane, incumbent, challenger, True, f"preferred by hand: {why}")


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
    """Write an adoption, or the loss, on the candidate that ran. #407.

    `spec` is what ran; `verdict.challenger` is used when it is one. The
    verdict lands on the candidate's proposal, or on the candidate alone for
    a typed default or a command-line spec, and never creates a proposal.
    """
    from harness import candidates
    from harness import memory_store as ms

    if is_reference(verdict.challenger):
        verdict = Verdict(verdict.lane, verdict.incumbent, verdict.challenger,
                          False, f"reference model; never a lane default "
                          f"({verdict.why})")
    outcome = "measured" if verdict.adopt else "declined"
    detail = f"{verdict.lane}: {verdict.why}"
    spec = spec or verdict.challenger
    # A text-lane spec is the proposal's own name; anything else maps by row.
    cid = candidates.ensure(conn, spec, proposal=spec, lane=verdict.lane)
    if cid is None:
        raise ValueError(f"{spec!r} is not a spec any runner takes, so an "
                         f"adoption of it could never be served")
    row = candidates.get(conn, spec)
    return ms.decide(conn, row["proposal"] or "", outcome, tier=TIER,
                     detail=detail[:200], candidate_id=cid, run_id=run_id)


def adopted(conn) -> dict[str, str]:
    """The lane -> spec the loop has adopted, newest per lane."""
    rows = conn.execute(
        "SELECT c.spec, v.detail, v.id FROM verdicts v "
        "JOIN candidates c ON c.id = v.candidate_id "
        "WHERE v.tier = ? AND v.outcome = 'measured' ORDER BY v.id",
        (TIER,)).fetchall()
    out = {}
    for row in rows:
        lane = str(row["detail"]).split(":", 1)[0].strip()
        if lane:
            out[lane] = row["spec"]
    return out


def default_for(lane: str, fallback: str, conn=None) -> str:
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
    close = conn is None
    try:
        if conn is None:
            from harness import memory_store as ms
            conn = ms.connect()
        got = adopted(conn).get(lane.strip().lower())
    except Exception:  # noqa: BLE001
        return fallback
    finally:
        if close and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    return got or fallback
