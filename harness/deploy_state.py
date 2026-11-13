"""A queue deploy's one declared lifecycle: its stages, the moves between them, and which release each stage says serves. #1731."""
from __future__ import annotations

# Stdlib only: deploy_switch runs it under the base interpreter with -I (#1610).

NEW = ""
BUILDING, SMOKING, MIGRATING, HANDED_OFF = "building", "smoking", "migrating", "handed_off"
SWITCHING, FLIPPED, INSTALLED, VERIFIED = "switching", "flipped", "installed", "verified"
ROLLING_BACK, FLIPPED_BACK, RESTORED, RESTORE_FAILED = "rolling_back", "flipped_back", "restored", "restore_failed"
ROLLBACK_INSTALLED, ROLLBACK_VERIFIED = "rollback_installed", "rollback_verified"
DEPLOYED, ROLLED_BACK, FAILED, INTERRUPTED = "deployed", "rolled_back", "failed", "interrupted"
#: A rollback whose store restore failed: the deploy failed and its own release still serves, on purpose (RULE #1417).
FAILED_FORWARD = "failed_forward"
#: A switch that died with no restart left while the store is past the previous release's schema: it waits on a repair. #1841.
STORE_AHEAD = "store_ahead"

#: The job's stages (deploys row), then the switch's (its record), then the outcomes; stage equals outcome once settled.
JOB_STAGES = (BUILDING, SMOKING, MIGRATING, HANDED_OFF)
SWITCH_STAGES = (SWITCHING, FLIPPED, INSTALLED, VERIFIED, ROLLING_BACK, FLIPPED_BACK, RESTORED, RESTORE_FAILED,
                 ROLLBACK_INSTALLED, ROLLBACK_VERIFIED)
OUTCOMES = (DEPLOYED, ROLLED_BACK, FAILED, FAILED_FORWARD, INTERRUPTED, STORE_AHEAD)
STAGES = (*JOB_STAGES, *SWITCH_STAGES, *OUTCOMES)
RUNNING = frozenset(JOB_STAGES + SWITCH_STAGES)
#: A dead switch settle will not start again whose release does not serve: closed so no reader takes it for live. #1971.
ABANDONED = "abandoned"
OUTCOMES, STAGES = (*OUTCOMES, ABANDONED), (*STAGES, ABANDONED)

#: Writers: the deploy job (harness/deploy.run), the switch (deploy_switch), and settle closing a row from its record.
JOB, SWITCH, SETTLE = "job", "switch", "settle"

_ROLLBACK = (ROLLING_BACK, FLIPPED_BACK, RESTORED, ROLLBACK_INSTALLED, ROLLBACK_VERIFIED)
#: Each legal move, (leaves, enters) -> the writers that may make it; check() refuses any other.
MOVES = {
    (NEW, BUILDING): {JOB},
    (BUILDING, BUILDING): {JOB},
    (BUILDING, SMOKING): {JOB},
    (SMOKING, MIGRATING): {JOB},
    (SMOKING, HANDED_OFF): {JOB},
    (MIGRATING, HANDED_OFF): {JOB},
    **{(s, FAILED): {JOB} for s in JOB_STAGES},
    (HANDED_OFF, SWITCHING): {SWITCH},
    (SWITCHING, FLIPPED): {SWITCH},
    (FLIPPED, INSTALLED): {SWITCH},
    (INSTALLED, VERIFIED): {SWITCH},
    (VERIFIED, DEPLOYED): {SWITCH},
    (SWITCHING, ROLLING_BACK): {SWITCH},
    (FLIPPED, ROLLING_BACK): {SWITCH},
    (INSTALLED, ROLLING_BACK): {SWITCH},
    (ROLLING_BACK, FLIPPED_BACK): {SWITCH},
    (FLIPPED_BACK, RESTORED): {SWITCH},
    (FLIPPED_BACK, RESTORE_FAILED): {SWITCH},
    (FLIPPED_BACK, ROLLBACK_INSTALLED): {SWITCH},
    (RESTORED, ROLLBACK_INSTALLED): {SWITCH},
    (ROLLBACK_INSTALLED, ROLLBACK_VERIFIED): {SWITCH},
    (ROLLBACK_INSTALLED, ROLLED_BACK): {SWITCH},
    (ROLLBACK_VERIFIED, ROLLED_BACK): {SWITCH},
    (RESTORE_FAILED, FAILED_FORWARD): {SWITCH},
    # Whatever raised in the switch ends it failed; a TERM leaves the stage and settle calls it interrupted.
    **{(s, FAILED): {SWITCH} for s in (SWITCHING, FLIPPED, INSTALLED, VERIFIED, *_ROLLBACK)},
}
# Settle closes a row from any running stage: a store restore rewinds the row to migrating (RULE #1347).
for _s in RUNNING:
    for _o in OUTCOMES:
        MOVES.setdefault((_s, _o), set()).add(SETTLE)

#: Which release a deploy at each stage says the deploy link serves: its own, the one before it, or no claim.
RELEASE, PREVIOUS, OTHER, NONE = "release", "previous", "other", "none"
EXPECT = {**{s: PREVIOUS for s in (*JOB_STAGES, SWITCHING, FLIPPED_BACK, RESTORED, ROLLBACK_INSTALLED,
                                   ROLLBACK_VERIFIED, ROLLED_BACK)},
          **{s: RELEASE for s in (FLIPPED, INSTALLED, VERIFIED, RESTORE_FAILED, DEPLOYED,
                                  FAILED_FORWARD)}}
#: How the deploy link stands against a deploy's stage.
AGREES, SPLIT, UNCLAIMED = "agrees", "split", "unclaimed"


class IllegalMove(RuntimeError):
    """A deploy move MOVES does not list, refused before anything is written. #1731."""


def check(leaves: str, enters: str, writer: str) -> None:
    if writer not in MOVES.get((leaves, enters), ()):
        raise IllegalMove(f"deploy: {writer} may not move it from {leaves or 'nothing'} to {enters}")


def outcome_of(rec: dict) -> str:
    """A switch record's outcome; an older switch wrote failed for a failed restore (RULE #1417)."""
    got = rec.get("outcome") or ""
    # The record says failed so an older release's settle still closes it (its MOVES lack abandoned). #1971.
    if got == FAILED and rec.get("abandoned"):
        return ABANDONED
    if got == FAILED and rec.get("stage") in (FAILED, RESTORE_FAILED) and rec.get("restore_failed"):
        return FAILED_FORWARD
    return got


def reconcile(stage: str, serves: str) -> str:
    """AGREES when the link serves what the stage says, SPLIT when it does not, UNCLAIMED when the stage says nothing."""
    want = EXPECT.get(stage, "")
    if not want:
        return UNCLAIMED
    return AGREES if serves == want else SPLIT
