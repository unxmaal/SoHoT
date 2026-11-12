"""This repo's gauntlet registry, handed to the pinned gauntlet package's ratchets and CLI (#492, #1785)."""

from pathlib import Path

from gauntlet.moves import MoveTable, reopens_by
from gauntlet.registry import Registry

from harness import adoption_state, deploy_state, download_state, exclusive, gateway_switch_state, job_state, paused, repo, sweeps
from tests.gauntlet import classes

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
# The agent lane's case repos are broken on purpose; they are inputs to a model, not code here.
NOT_PRODUCTION = ("tests/", "evals/cases/")
# Unbound hits pinned when the detectors landed; lower it as the backlog is bound.
BACKLOG_PIN = 60


def production(rel):
    return not rel.startswith(NOT_PRODUCTION)


MOVES = (
    MoveTable("harness/job_state.py:MOVES", job_state.MOVES, initial=(job_state.PENDING,),
              terminal=(job_state.DONE, job_state.FAILED, job_state.CANCELLED),
              states=(job_state.PENDING, job_state.RUNNING, job_state.DONE, job_state.FAILED, job_state.CANCELLED,
                      job_state.PAUSED)),
    MoveTable("harness/paused.py:MOVES", paused.MOVES, initial=(None,),
              terminal=(paused.STALE, paused.DONE, paused.DEFECT), states=paused.STATES),
    MoveTable("harness/deploy_state.py:MOVES", deploy_state.MOVES, initial=(deploy_state.NEW,),
              terminal=deploy_state.OUTCOMES, states=deploy_state.STAGES),
    MoveTable("harness/sweeps.py:MOVES", sweeps.MOVES, initial=(None,), terminal=sweeps.SETTLED + sweeps.FOUND,
              reopens=reopens_by(sweeps.MOVES, {sweeps.REFILED}), states=(sweeps.OPEN, *sweeps.SETTLED, *sweeps.FOUND)),
    MoveTable("harness/download_state.py:MOVES", download_state.MOVES, initial=(download_state.NONE,),
              terminal=(download_state.REMOVED,), states=download_state.STATES),
    MoveTable("harness/gateway_switch_state.py:MOVES", gateway_switch_state.MOVES, initial=(gateway_switch_state.NONE,),
              terminal=(gateway_switch_state.SERVING, gateway_switch_state.FAILED), states=gateway_switch_state.STATES),
    # Keyed (state, move) -> state; the check reads (leaves, enters) pairs.
    MoveTable("harness/adoption_state.py:MOVES", {(frm, to) for (frm, _), to in adoption_state.MOVES.items()},
              initial=(adoption_state.NONE, adoption_state.CONFIGURED), states=adoption_state.STATES),
)

MOVE_WAIVERS = {
    "harness/exclusive.py:MOVES": f"#1821: state_of derives {exclusive.ABANDONED!r} when a holder dies, but no move "
                                  "enters it, so the check finds it unreachable; register it when #1821 lists that move",
}

REGISTRY = Registry(
    root=REPO,
    index=classes.INDEX, pending=classes.PENDING, unclassified=classes.UNCLASSIFIED,
    snapshot_file=HERE / "skill_classes.json", defects_file=HERE / "defects.json",
    backlog_file=HERE / "backlog.json", backlog_pin=BACKLOG_PIN,
    repo_slug="unxmaal/SoHoT",
    production=production,
    code_paths=r"^(?:harness/|scripts/|evals/(?!cases/))",
    files=repo.publishable,
    moves=MOVES,
    move_waivers=MOVE_WAIVERS,
)
