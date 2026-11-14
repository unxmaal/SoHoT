"""Tier-2 trigger detectors: each hit is bound to a test, waived with a reason, or in the shrinking backlog (#492 B, #1785)."""

import re

import gauntlet.ratchet
import pytest
from gauntlet import detectors, moves

from harness import exclusive
from tests import tree_cache
from tests.gauntlet import registry
from tests.gauntlet.registry import REGISTRY

DETECTOR_HALF = ("test_gauntlet_no_new_code_trips_a_detector_without_a_bound_test",
                 "test_gauntlet_the_backlog_only_shrinks", "test_gauntlet_no_binding_or_waiver_is_stale",
                 "test_gauntlet_every_move_table_is_sound", "test_gauntlet_every_move_table_is_registered")
_RATCHETS = gauntlet.ratchet.tests(REGISTRY)
PAIRED = '''import json
import time

def add(conn):
    conn.execute("INSERT INTO a (x) VALUES (1)")
    conn.commit()
    return 1

def link(conn):
    i = add(conn)
    conn.execute("INSERT INTO b (a_id) VALUES (?)", (i,))

def load(p):
    out = []
    for line in open(p):
        try:
            out.append(json.loads(line))
        except ValueError:
            break
    return out

def append(p, row):
    with open(p, "a") as f:
        f.write(json.dumps(row) + "\\n")

def wait(ready):
    while not ready():
        time.sleep(1)
'''
globals().update({name: _RATCHETS[name] for name in DETECTOR_HALF})


@pytest.fixture(autouse=True)
def _kept_hits(monkeypatch):
    """The detectors' whole-tree hits come from the tree cache until a production source changes (#1590)."""
    monkeypatch.setattr(gauntlet.ratchet, "frontend_hits", tree_cache.frontend_hits)


def test_each_open_issue_binding_names_a_backlog_row_of_its_class():
    """#1830: a fixed site leaves the backlog, and then its issue binding goes too."""
    backlog = REGISTRY.backlog()
    dead = [f"#{n} {cid}: {pat}" for n, (cid, pats) in registry.OPEN_ISSUES.items() for pat in pats
            if not any(re.search(pat, s) for s in backlog.get(cid, []))]
    assert not dead, "drop these from registry.OPEN_ISSUES, or close the issue:\n  " + "\n  ".join(dead)


def test_the_two_detector_classes_report_both_halves():
    """#1830: each class the corpus gives two detectors runs both, and the wait half still gets the move tables."""
    trees = detectors.parse({"harness/q.py": PAIRED})
    config = gauntlet.ratchet.detector_config(REGISTRY)
    # A qualified committer must name a definition in the tree it scans; this one-file tree has no memory_store.
    config.pop("commit_then_link")
    hits = detectors.run(trees, REGISTRY.index, REGISTRY.production, None, config)
    assert {h.site for h in hits[registry.CR]} == {"harness/q.py:link", "harness/q.py:append"}
    assert {"harness/q.py:wait", "harness/job_state.py:MOVES:done"} <= {h.site for h in hits[registry.WT]}


def test_the_agent_lane_s_deliberately_broken_case_repos_are_not_production():
    assert REGISTRY.production("harness/cli.py") and REGISTRY.production("evals/run.py")
    assert not REGISTRY.production("evals/cases/repo/x/app.py")
    assert not REGISTRY.production("tests/test_x.py")


def test_exclusive_moves_is_registered_and_sound():
    """#1821: the gpu lease table lists the move a holder's death makes into abandoned."""
    table = next(t for t in registry.MOVES if t.site == "harness/exclusive.py:MOVES")
    assert table.findings() == []
    assert "harness/exclusive.py:MOVES" not in registry.MOVE_WAIVERS
    assert moves.MoveTable(table.site, exclusive.MOVES, initial=(exclusive.FREE,)).findings() == []