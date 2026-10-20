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


# --- the limit and its until, exactly -----------------------------------------------

SHORT = {"cases": 10, "cases_needed": 40, "effect": 0.2, "cap": 16, "power": 0.3, "target": 0.8}


def test_a_holdout_short_of_its_need_says_how_many_more_cases_and_for_whom():
    assert adopt.lane_limit("svg", SHORT, "org/m") == (100, (
        "lane too small, needs 40 holdout cases: 10 cannot show +0.20 per cell at power 0.8 at any repeat "
        "up to 16, so about 100 more svg cases are needed before a null says anything about org/m"))
    assert adopt.lane_limit("svg", SHORT)[1].endswith("says anything about a challenger")
    bare = adopt.lane_limit("svg", {"cases_needed": 3, "power": 0.1})
    assert bare[1].startswith("lane too small, needs 3 holdout cases: 0 cannot show +0.00 per cell")


@pytest.mark.parametrize("plan", [
    {**SHORT, "power": 0.8}, {**SHORT, "power": 0.9}, {**SHORT, "target": 0.3, "power": 0.3},
    {**SHORT, "unmeasured": True}, {**SHORT, "unmeasured": True, "power": 0.0},
    {**SHORT, "cases_needed": 10}, {**SHORT, "cases_needed": None},
    {"cases": 3, "odds": [0.1, 0.0]}, {"cases": 3, "max_power": 0.01}])
def test_a_plan_with_power_left_at_some_repeat_is_no_lane_limit(plan):
    assert adopt.lane_limit("svg", plan, "org/m") is None


def test_a_target_the_plan_names_is_the_one_its_message_quotes():
    assert "at power 0.5 at any repeat" in adopt.lane_limit("svg", {**SHORT, "target": 0.5, "power": 0.4})[1]


@pytest.mark.parametrize("odds", [[0.0, 0.3], [0.0, 0.0], [-0.1, 0.2]])
def test_an_incumbent_passing_every_case_is_a_limit_one_case_away(odds):
    assert adopt.lane_limit("svg", {"cases": 3, "odds": odds, "power": 0.0, "cap": 16}) == (
        1, "lane too small, needs cases the incumbent fails: it passes all 3 holdout cases, "
           "so no challenger can show a gain on them")


@pytest.mark.parametrize("max_power", [0.0, -0.0])
def test_a_plan_at_power_0_at_the_largest_effect_is_a_limit_one_case_away(max_power):
    assert adopt.lane_limit("svg", {"cases": 3, "max_power": max_power, "power": 0.0, "cap": 16}) == (
        1, "lane too small: 3 holdout cases give power 0 even at +1.00 per cell at every repeat up to 16")


@pytest.mark.parametrize("cases,need,more", [
    (10, 40, 100), (None, 10, 34), (0, 10, 34), (10, 20, 34), (10, 11, 4), (None, 1, 4),
    (10, 10, 1), (10, 5, 1), (10, None, 1)])
def test_the_cases_a_lane_needs_scale_by_the_holdout_fraction(cases, need, more):
    assert adopt.more_cases(cases, need) == more


def test_a_lane_until_waits_on_one_more_case_unless_told_more():
    assert adopt.cases_until("svg", 3) == "cases:svg>3"
    assert adopt.cases_until("svg", 3, 5) == "cases:svg>7"


def _sized(monkeypatch, sizes):
    def for_lane(lane, *a, **k):
        n = sizes[lane]
        return holdout.Split(lane, tuple(f"d{i}" for i in range(n)), tuple(f"h{i}" for i in range(n)), False)
    monkeypatch.setattr(holdout, "for_lane", for_lane)


def test_the_cases_a_lane_has_are_its_own_split_s_else_the_plan_s(monkeypatch):
    _sized(monkeypatch, {"svg": 4, "code": 9})
    assert adopt._have("svg", None, 99) == 8
    assert adopt._have("code", None, 99) == 18
    assert adopt._have("svg", holdout.Split("svg", ("a",), ("a", "b"), False), 99) == 2
    assert adopt._have("svg", holdout.Split("svg", (), (), False), 7) == 7


SHORT_PLAN = power.plan([0.6] * 5, 0.2, stochastic=False, observed=5, rho=1.0)
EXTRACT = holdout.Split("extract", ("d1", "d2", "d3"), ("h1", "h2", "h3", "h4", "h5"), False)
NEEDS = ("lane too small, needs 91 holdout cases: 5 cannot show +0.20 per cell at power 0.8 at any repeat up to 16, "
         "so about 287 more extract cases are needed before a null says anything about ch")


def _decided(split):
    rows = [r for c in EXTRACT.holdout for r in ({"candidate": "inc", "case_id": c, "passed": True, "seconds": 1.0},
                                                 {"candidate": "ch", "case_id": c, "passed": True, "seconds": 1.0})]
    summary = {"pass_rate": 1.0, "median_s": 1.0, "metrics": {}}
    return adopt.decide("extract", {**summary, "candidate": "inc"}, {**summary, "candidate": "ch"}, rows,
                        split=split, plan=SHORT_PLAN, spec="org/model")


def test_a_null_on_a_too_small_lane_names_both_sides_and_waits_on_that_lane(monkeypatch):
    _sized(monkeypatch, {"extract": 0})
    for split, until in ((EXTRACT, "cases:extract>294"), (None, "cases:extract>291")):
        got = _decided(split)
        assert (got.lane, got.incumbent, got.challenger, got.adopt) == ("extract", "inc", "ch", False)
        assert (got.failure_class, got.until) == (reasons.LANE_TOO_SMALL, until)
        assert got.why.startswith(f"{NEEDS} (") and "no gain up to +1.00 is detectable at power 0.8" in got.why


def test_a_plan_no_run_can_decide_is_a_verdict_written_without_running_it(monkeypatch):
    _sized(monkeypatch, {"extract": 0})
    why = f"{NEEDS}; not run: power 0.00 at +1.00 per cell, so no run of this holdout can decide"
    assert adopt.undecidable("extract", "inc", "ch", SHORT_PLAN, EXTRACT) == adopt.Verdict(
        "extract", "inc", "ch", False, why, failure_class=reasons.LANE_TOO_SMALL,
        evidence={"power": SHORT_PLAN.as_dict(), "split": EXTRACT.as_dict()}, until="cases:extract>294")
    assert adopt.undecidable("extract", "inc", "ch", SHORT_PLAN) == adopt.Verdict(
        "extract", "inc", "ch", False, why, failure_class=reasons.LANE_TOO_SMALL,
        evidence={"power": SHORT_PLAN.as_dict()}, until="cases:extract>291")
    assert adopt.undecidable("extract", "inc", "ch", dataclasses.replace(SHORT_PLAN, max_power=0.1)) is None
