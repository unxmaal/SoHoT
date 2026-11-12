"""Tier-2 trigger detectors: each hit is bound to a test, waived with a reason, or in the shrinking backlog (#492 B, #1785)."""

import gauntlet.ratchet
from gauntlet import moves

from harness import exclusive
from tests.gauntlet import registry
from tests.gauntlet.registry import REGISTRY

DETECTOR_HALF = ("test_gauntlet_no_new_code_trips_a_detector_without_a_bound_test",
                 "test_gauntlet_the_backlog_only_shrinks", "test_gauntlet_no_binding_or_waiver_is_stale",
                 "test_gauntlet_every_move_table_is_sound", "test_gauntlet_every_move_table_is_registered")
_RATCHETS = gauntlet.ratchet.tests(REGISTRY)
globals().update({name: _RATCHETS[name] for name in DETECTOR_HALF})


def test_the_agent_lane_s_deliberately_broken_case_repos_are_not_production():
    assert REGISTRY.production("harness/cli.py") and REGISTRY.production("evals/run.py")
    assert not REGISTRY.production("evals/cases/repo/x/app.py")
    assert not REGISTRY.production("tests/test_x.py")


def test_the_exclusive_waiver_stands_only_while_its_table_is_unsound():
    """#1821: when exclusive.MOVES lists the move into abandoned, register it instead of waiving it."""
    table = moves.MoveTable("harness/exclusive.py:MOVES", exclusive.MOVES, initial=(exclusive.FREE,))
    assert table.findings(), "exclusive.MOVES is sound now: move it from MOVE_WAIVERS into MOVES in the registry"
    assert "harness/exclusive.py:MOVES" in registry.MOVE_WAIVERS
