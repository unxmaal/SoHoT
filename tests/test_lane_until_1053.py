"""#1053: a cases until counts the lane as it was when the verdict was decided, not as it is now."""
import dataclasses
import json

import pytest

from harness import adopt, coherence, holdout, live_audit, reasons
from harness import memory_store as ms
from harness.memory_store import transitions

T = 1791000000.0
GROWN = 643
SATURATED = {"repeat": 1, "power": 0.0, "cells": 3, "cases": 3, "effect": 0.2, "target": 0.8, "cap": 16,
             "cases_needed": None, "side": "holdout", "cases_run": 3, "unmeasured": False, "odds": [0.0, 0.0]}


@pytest.fixture
def grown(monkeypatch):
    split = holdout.Split("svg", tuple(f"d{i}" for i in range(GROWN - 195)), tuple(f"h{i}" for i in range(195)),
                          False)
    one = holdout.Split("other", ("o",), ("o",), True)
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: split if lane == "svg" else one)
    return split


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _held(conn, name):
    return conn.execute("SELECT p.next_retest_at, v.until, v.failure_class FROM proposals p "
                        "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()


def _screened(conn, name, lane):
    got = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()
    if got:
        return got[0]
    ms.record(conn, ms.Seen(name=name, source="t", lane=lane, resolved=name))
    ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T)
    return conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]


def _declined(conn, name, plan, lane="svg", until="", failure_class=reasons.UNDERPOWERED, retest=True,
              detail="underpowered"):
    pid = _screened(conn, name, lane)
    vid = transitions._write(conn, pid, name, {"outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT,
                                               "until": until, "detail": f"{lane}: {detail}", "decided_at": T,
                                               "failure_class": failure_class})
    conn.execute("UPDATE verdicts SET power = ?, split_version = '1' WHERE id = ?", (json.dumps(plan), vid))
    if retest:
        conn.execute("UPDATE proposals SET next_retest_at = ? WHERE id = ?", (T + ms.RETEST_AFTER_SECONDS, pid))
    conn.commit()


def test_the_split_wins_then_the_plan_and_never_more_than_the_lane_has(grown):
    split = {"dev": ["a", "b", "c", "d"], "holdout": ["e", "f"]}
    assert adopt.decided_cases("svg", split, SATURATED) == 6
    assert adopt.decided_cases("svg", None, {**SATURATED, "side": "all", "cases_run": 5}) == 5
    assert adopt.decided_cases("svg", None, SATURATED) == 3, "a 3-case holdout may be a lane too small to split"
    assert adopt.decided_cases("svg", None, {"cases": 30, "side": "holdout"}) == 100
    assert adopt.decided_cases("svg", None, {"cases": 600, "side": "holdout"}) == GROWN
    assert adopt.decided_cases("svg") == GROWN
    assert adopt.decided_cases("svg", None, {"cases": 6, "side": "holdout"}) == 20, "6 holdout cases is a split lane"
    assert adopt.decided_cases("web", None, {"cases": 3, "side": "holdout"}) == 1, "clamped to the web lane, not svg"
    assert (adopt.lane_cases("svg"), adopt.lane_cases("web")) == (GROWN, 1)


def test_13008_and_13009_wait_on_the_three_cases_they_were_decided_on(store, grown):
    _declined(store, "OmniSVG/OmniSVG1.1_4B", {**SATURATED, "side": "all"})
    _declined(store, "OmniSVG/OmniSVG1.1_8B", SATURATED)
    found = coherence.changes(store)
    assert {c["name"]: c["now"][3] for c in found} == {
        "OmniSVG/OmniSVG1.1_4B": "cases:svg>3", "OmniSVG/OmniSVG1.1_8B": "cases:svg>3"}
    coherence.apply(store, found)
    assert ms.revisitable(store, {"cases": {"svg": GROWN}}), "the grown lane reopens both"


def test_a_spent_limit_with_no_lane_reason_waits_on_the_lane_it_was_decided_on(store, grown):
    plan = {"cases": 5, "cases_needed": None, "side": "holdout", "power": 0.63}
    _declined(store, "plan:q3-4b", plan, retest=False)
    _declined(store, "plan:q3-4b", plan, retest=False, detail="underpowered again")
    assert [c["now"][3] for c in coherence.changes(store)] == ["cases:svg>5"]


def test_the_adopt_writer_counts_the_plan_when_the_verdict_has_no_split(store, grown):
    pid = _screened(store, "org/m", "svg")
    plan = {"repeat": 1, "power": 0.63, "cells": 3, "cases": 3, "cases_needed": None, "side": "holdout"}
    verdict = adopt.Verdict("svg", "inc", "org/m", False, "underpowered: power 0.63 < 0.8",
                            failure_class=reasons.UNDERPOWERED, evidence={"power": plan})
    adopt.record(store, verdict, spec="org/m")
    assert ms.reopen_due_retests(store, now=_held(store, "org/m")["next_retest_at"] + 1) == ["org/m"]
    ms.decide(store, "org/m", "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE)
    adopt.record(store, verdict, spec="org/m")
    assert transitions.retest_spent(store, pid, ms.ADOPT)
    assert _held(store, "org/m")["until"] == "cases:svg>3"


def test_an_until_written_from_the_grown_lane_is_brought_back(store, grown):
    _declined(store, "OmniSVG/OmniSVG1.1_8B", SATURATED, until=f"cases:svg>{GROWN}",
              failure_class=reasons.LANE_TOO_SMALL, retest=False)
    _declined(store, "LiquidAI/LFM2.5-2.6B", {"cases": 135, "cases_needed": 135, "side": "holdout",
                                             "power": 0.5}, lane="code", until="cases:code>451", retest=False)
    _declined(store, "best-of:3:q3-30b", {**SATURATED, "side": "all"}, until="cases:svg>3",
              failure_class=reasons.LANE_TOO_SMALL, retest=False)
    found = coherence.changes(store)
    assert {c["name"]: c["now"][3] for c in found} == {"OmniSVG/OmniSVG1.1_8B": "cases:svg>3"}
    coherence.apply(store, found)
    assert _held(store, "OmniSVG/OmniSVG1.1_8B")["failure_class"] == reasons.LANE_TOO_SMALL
    assert coherence.changes(store) == []
    assert live_audit._terminal_reason_coherent(store) == ([], [])
