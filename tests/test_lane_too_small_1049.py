"""#1049: a saturated or too-small holdout is lane_too_small for a model and a method alike, and a plan at power 0 is not run."""
import argparse
import dataclasses
import json

import pytest

from harness import adopt, candidates, coherence, holdout, live_audit, power, reasons, screen
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from harness.memory_store import transitions

T = 1791000000.0
SVG = holdout.Split("svg", ("s1", "s2", "s3"), ("s1", "s2", "s3"), True)
SPECS = [("OmniSVG/OmniSVG1.1_8B", "omnisvg:8B"), ("best-of:3:q3-30b", "best-of:3:q3-30b")]


@pytest.fixture
def svg_lane(monkeypatch):
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: dataclasses.replace(SVG, lane=lane))
    return SVG


def _saturated(**kw):
    return power.plan([1.0] * 3, 0.2, stochastic=True, observed=69, **kw)


def _rows(passed=True):
    return [r for c in SVG.holdout for r in ({"candidate": "q3-30b", "case_id": c, "passed": True, "seconds": 1.0},
                                             {"candidate": "ch", "case_id": c, "passed": passed, "seconds": 1.0})]


def _held(conn, name):
    return conn.execute("SELECT p.state, p.next_retest_at, v.tier, v.reason, v.until, v.failure_class, v.run_id, "
                        "v.detail FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                        "WHERE p.name = ?", (name,)).fetchone()


# --- the plan knows ---------------------------------------------------------------

def test_a_saturated_holdout_has_power_0_even_at_the_largest_effect():
    plan = _saturated()
    assert plan.max_power == 0.0 and power.undecidable(plan)


def test_three_deterministic_cases_cannot_decide_even_when_the_incumbent_fails_them():
    plan = power.plan([0.0] * 3, 0.2, stochastic=False, observed=3, rho=1.0)
    assert plan.odds is None and plan.max_power == 0.0 and power.undecidable(plan)


def test_repeats_that_may_be_independent_can_still_decide_a_small_holdout():
    plan = power.plan([0.0] * 3, 0.2, stochastic=True, observed=3)
    assert plan.max_power > 0 and not power.undecidable(plan), "an unmeasured rho is not assumed to be 1 here"


def test_a_guessed_plan_is_never_skipped():
    assert not power.undecidable(dataclasses.replace(_saturated(), unmeasured=True))


def test_a_lane_with_room_to_gain_is_run():
    assert not power.undecidable(power.plan([0.5] * 40, 0.2, stochastic=True, observed=40, rho=0.0))


# --- one rule at decide -----------------------------------------------------------

@pytest.mark.parametrize("name,spec", SPECS)
def test_a_model_and_a_method_on_a_saturated_holdout_wait_on_the_lane(name, spec, svg_lane):
    summary = {"pass_rate": 1.0, "median_s": 1.0, "metrics": {}}
    plan = dataclasses.replace(_saturated(), odds=power._cell_odds([1.0] * 3, 0.2))
    got = adopt.decide("svg", {**summary, "candidate": "q3-30b"}, {**summary, "candidate": "ch"}, _rows(),
                       split=SVG, plan=plan, spec=spec)
    assert got.failure_class == reasons.LANE_TOO_SMALL, got.why
    assert got.until == "cases:svg>3"
    assert got.why.startswith("lane too small, needs cases the incumbent fails")


def test_a_model_on_a_lane_its_plan_says_is_too_small_names_the_cases_it_needs():
    plan = power.plan([0.6] * 5, 0.2, stochastic=False, observed=5, rho=1.0)
    split = holdout.Split("extract", ("d1", "d2", "d3"), ("h1", "h2", "h3", "h4", "h5"), False)
    rows = [r for c in split.holdout for r in ({"candidate": "inc", "case_id": c, "passed": True, "seconds": 1.0},
                                               {"candidate": "ch", "case_id": c, "passed": True, "seconds": 1.0})]
    summary = {"pass_rate": 1.0, "median_s": 1.0, "metrics": {}}
    got = adopt.decide("extract", {**summary, "candidate": "inc"}, {**summary, "candidate": "ch"}, rows,
                       split=split, plan=plan, spec="org/model")
    assert got.failure_class == reasons.LANE_TOO_SMALL and got.until.startswith("cases:extract>")


# --- measure writes the verdict from the plan --------------------------------------

@pytest.mark.parametrize("name,spec", SPECS)
def test_measure_does_not_run_a_plan_that_cannot_decide(name, spec, svg_lane, monkeypatch):
    launched = []
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: launched.append(argv))
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "q3-30b")
    monkeypatch.setattr(candidates, "for_proposal", lambda store, lane, name, attaches="": spec)
    monkeypatch.setattr(screen, "routed_gateway", lambda name: "")
    plan = dataclasses.replace(_saturated(), odds=(0.0, 0.0))
    monkeypatch.setattr(measure_cmd, "_plan", lambda a, lane, inc, sp, sweep=None: (SVG, plan))
    conn = ms.connect()
    try:
        ms.record(conn, ms.Seen(name=name, source="t", lane="svg", resolved=name))
        ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE)
        candidates.ensure(conn, spec, proposal=name, lane="svg")
    finally:
        conn.close()
    assert measure_cmd._measure_and_adopt(argparse.Namespace(repeat=None), {"name": name, "lane": "svg"}) == 0
    assert launched == [], "a plan at power 0 at +1.00 launches no evals.run"
    conn = ms.connect()
    try:
        got = _held(conn, name)
        assert (got["state"], got["tier"], got["reason"], got["failure_class"]) == (
            "declined", ms.ADOPT, reasons.LIMIT, reasons.LANE_TOO_SMALL)
        assert got["until"] == "cases:svg>3" and got["next_retest_at"] is None and got["run_id"] is None
        assert "not run: power 0.00 at +1.00" in got["detail"]
        assert adopt.comparisons(conn, "svg", SVG.version) == 0
        assert live_audit._terminal_reason_coherent(conn) == ([], [])
    finally:
        conn.close()


# --- soh coherence moves the time retests to the lane --------------------------------

def _live_svg(conn, name, plan, lane="svg"):
    """13008/13009 as the 2026-10-19 day loop left them: adopt underpowered, until '', a time retest."""
    ms.record(conn, ms.Seen(name=name, source="t", lane=lane, resolved=name))
    ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T)
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    vid = transitions._write(conn, pid, name, {"outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT,
                                               "until": "", "detail": f"{lane}: underpowered: power 0.00",
                                               "decided_at": T, "failure_class": reasons.UNDERPOWERED})
    conn.execute("UPDATE verdicts SET power = ?, split_version = '1' WHERE id = ?", (json.dumps(plan), vid))
    conn.execute("UPDATE proposals SET next_retest_at = ? WHERE id = ?", (T + ms.RETEST_AFTER_SECONDS, pid))
    conn.commit()


LIVE_13009 = {"repeat": 1, "power": 0.0, "cells": 3, "cases": 3, "effect": 0.2, "alpha": 0.025, "target": 0.8,
              "cap": 16, "stochastic": True, "observed": 81, "rho": 1.0, "rho_measured": False,
              "cases_needed": None, "side": "holdout", "cases_run": 3, "mde": None, "unmeasured": False,
              "odds": [0.0, 0.0]}


def test_soh_coherence_moves_a_saturated_time_retest_to_the_lane_until(svg_lane, tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        _live_svg(conn, "OmniSVG/OmniSVG1.1_4B", {**LIVE_13009, "side": "all"})
        _live_svg(conn, "OmniSVG/OmniSVG1.1_8B", LIVE_13009)
        _live_svg(conn, "org/powered", {**LIVE_13009, "cases": 135, "cases_needed": 135,
                                        "odds": [0.16, 0.04], "power": 0.63}, lane="code")
        found = coherence.changes(conn)
        assert {c["name"]: c["now"] for c in found} == {
            "OmniSVG/OmniSVG1.1_4B": ["declined", "adopt", "limit", "cases:svg>3"],
            "OmniSVG/OmniSVG1.1_8B": ["declined", "adopt", "limit", "cases:svg>3"]}
        coherence.apply(conn, found)
        for name in ("OmniSVG/OmniSVG1.1_4B", "OmniSVG/OmniSVG1.1_8B"):
            got = _held(conn, name)
            assert (got["failure_class"], got["until"], got["next_retest_at"]) == (
                reasons.LANE_TOO_SMALL, "cases:svg>3", None)
        assert _held(conn, "org/powered")["next_retest_at"] is not None, "a lane with the cases keeps its retest"
        assert coherence.changes(conn) == []
        assert live_audit._terminal_reason_coherent(conn) == ([], [])
    finally:
        conn.close()


def test_a_lane_that_grew_since_the_plan_is_reopened_by_its_until(monkeypatch, tmp_path):
    grown = holdout.Split("svg", tuple(f"d{i}" for i in range(9)), tuple(f"h{i}" for i in range(4)), False)
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: grown)
    conn = ms.connect(tmp_path / "s.db")
    try:
        _live_svg(conn, "OmniSVG/OmniSVG1.1_4B", {**LIVE_13009, "side": "all"})
        coherence.apply(conn, coherence.changes(conn))
        assert ms.revisitable(conn, {"cases": {"svg": 13}}), "planned on 3 cases, the lane now has 13"
    finally:
        conn.close()
