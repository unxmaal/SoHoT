"""#1001: an adopt limit decline after its one retest, the web method nulls, and the soh coherence repair."""
import dataclasses
import json
import sqlite3

import pytest

from harness import adopt, coherence, holdout, live_audit, power, reasons
from harness import memory_store as ms
from harness.memory_store import transitions

T = 1791000000.0
LANE_CASES = 9


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


@pytest.fixture
def lane_cases(monkeypatch):
    split = holdout.Split("code", tuple(f"d{i}" for i in range(6)), tuple(f"h{i}" for i in range(3)), False)
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: dataclasses.replace(split, lane=lane))
    return split


def _held(conn, name):
    return conn.execute("SELECT p.state, p.retest_count, p.next_retest_at, v.tier, v.reason, v.until, "
                        "v.failure_class FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                        "WHERE p.name = ?", (name,)).fetchone()


def _underpowered(lane="code", spec="org/m", need=None, cases=3):
    plan = {"repeat": 1, "power": 0.63, "cells": cases, "cases": cases, "cases_needed": need}
    return adopt.Verdict(lane, "inc", spec, False, "underpowered: power 0.63 < 0.8 (does not beat the incumbent)",
                         failure_class=reasons.UNDERPOWERED,
                         evidence={"power": plan, "split": {"lane": lane, "version": holdout.VERSION,
                                                            "too_small": False,
                                                            "dev": [f"d{i}" for i in range(6)],
                                                            "holdout": [f"h{i}" for i in range(3)]}})


def _retested_once(conn, name="org/m", lane="code"):
    ms.record(conn, ms.Seen(name=name, source="t", lane=lane, resolved=name))
    ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T)
    adopt.record(conn, _underpowered(lane, name), spec=name)
    first = _held(conn, name)
    assert first["next_retest_at"] is not None and first["until"] == "", "the first decline gets its retest"
    assert ms.reopen_due_retests(conn, now=first["next_retest_at"] + 1) == [name]
    ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE)


def test_an_adopt_decline_after_its_retest_waits_on_the_lane_growing(store, lane_cases):
    _retested_once(store)
    adopt.record(store, _underpowered(), spec="org/m")
    got = _held(store, "org/m")
    assert (got["state"], got["retest_count"], got["next_retest_at"]) == ("declined", 1, None)
    assert got["until"] == f"cases:code>{LANE_CASES}", "no retest is left, so a limit names what lifts it"
    assert live_audit._terminal_reason_coherent(store) == ([], [])


def test_the_lane_until_asks_for_the_cases_the_plan_needs(store, lane_cases):
    _retested_once(store)
    adopt.record(store, _underpowered(need=6), spec="org/m")
    assert _held(store, "org/m")["until"] == f"cases:code>{LANE_CASES + 10 - 1}"


def test_a_first_adopt_decline_still_gets_its_retest_and_no_until(store, lane_cases):
    ms.record(store, ms.Seen(name="org/m", source="t", lane="code", resolved="org/m"))
    ms.decide(store, "org/m", "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE)
    adopt.record(store, _underpowered(), spec="org/m")
    got = _held(store, "org/m")
    assert got["until"] == "" and got["next_retest_at"] is not None


def test_a_candidate_loss_after_its_retest_is_settled_with_no_until(store, lane_cases):
    _retested_once(store)
    adopt.record(store, adopt.Verdict("code", "inc", "org/m", False, "significantly worse"), spec="org/m")
    got = _held(store, "org/m")
    assert (got["reason"], got["until"], got["next_retest_at"]) == (reasons.CANDIDATE, "", None)
    assert live_audit._terminal_reason_coherent(store) == ([], [])


def test_the_writer_never_refuses_a_retest_tier_limit_mid_sweep(store):
    _retested_once(store)
    pid = store.execute("SELECT id FROM proposals WHERE name = 'org/m'").fetchone()[0]
    store.execute("INSERT INTO verdicts (proposal_id, outcome, tier, reason, decided_at) "
                  "VALUES (?, 'declined', 'adopt', 'limit', ?)", (pid, T))
    ms.decide(store, "org/m", "declined", tier=ms.ADOPT, reason=reasons.LIMIT)
    assert transitions.retest_spent(store, pid, ms.ADOPT)


def _stored_plan(**kw):
    """The power JSON of live verdict 12681 (plan:q3-4b, web, 5 cases, incumbent passes all)."""
    raw = {"repeat": 2, "power": 0.0, "cells": 5, "cases": 5, "effect": 0.2, "alpha": 0.0167, "target": 0.8,
           "cap": 16, "capped": False, "stochastic": True, "observed": 70, "why": "the holdout is saturated",
           "rho": 1.0, "cases_needed": None, "needed_repeat": 2, "side": "all", "calls": 3, "cases_run": 5,
           "mde": None, "unmeasured": False, "odds": [0.0, 0.0], "sweeps": 1, "comparisons": 3, **kw}
    names = {f.name for f in dataclasses.fields(power.Plan)}
    return power.Plan(**{k: v for k, v in raw.items() if k in names})


@pytest.mark.parametrize("spec", ["plan:q3-4b", "best-of:3:q3-4b"])
def test_todays_code_calls_the_live_web_method_nulls_lane_too_small(spec):
    cases = [f"w{i}" for i in range(5)]
    split = holdout.Split("web", tuple(cases), tuple(cases), True)
    rows = [r for c in cases for r in ({"candidate": "q3-4b", "case_id": c, "passed": True, "seconds": 1.0},
                                       {"candidate": "ch", "case_id": c, "passed": True, "seconds": 1.0})]
    summary = {"pass_rate": 1.0, "median_s": 1.0, "metrics": {}}
    got = adopt.decide("web", {**summary, "candidate": "q3-4b"}, {**summary, "candidate": "ch"}, rows,
                       split=split, plan=_stored_plan(), spec=spec)
    assert got.failure_class == reasons.LANE_TOO_SMALL, got.why
    assert got.until == "cases:web>5" and got.why.startswith("lane too small, needs cases the incumbent fails")


# --- soh coherence repairs the kind ---------------------------------------------

def _live_three(conn):
    """12680-12682 as the pre-#992 loop left them: adopt limit declines after a retest, no until, no retest."""
    for name, lane, plan in (("LiquidAI/LFM2.5-2.6B", "code", {"cases": 135, "cases_needed": 135}),
                             ("plan:q3-4b", "web", {"cases": 5, "cases_needed": None}),
                             ("best-of:3:q3-4b", "web", {"cases": 5, "cases_needed": None})):
        _retested_once(conn, name, lane)
        pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
        vid = transitions._write(conn, pid, name, {"outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT,
                                                   "until": "", "detail": f"{lane}: underpowered", "decided_at": T,
                                                   "failure_class": reasons.UNDERPOWERED})
        conn.execute("UPDATE verdicts SET power = ? WHERE id = ?", (json.dumps(plan), vid))
    conn.commit()


def test_soh_coherence_gives_a_spent_adopt_limit_its_lane_until(store, lane_cases):
    _live_three(store)
    assert len(live_audit._terminal_reason_coherent(store)[0]) == 3
    found = coherence.changes(store)
    assert {c["name"]: c["now"] for c in found} == {
        "LiquidAI/LFM2.5-2.6B": ["declined", "adopt", "limit", f"cases:code>{LANE_CASES}"],
        "plan:q3-4b": ["declined", "adopt", "limit", "cases:web>5"],
        "best-of:3:q3-4b": ["declined", "adopt", "limit", "cases:web>5"],
    }
    assert len(coherence.apply(store, found)) == 3
    assert live_audit._terminal_reason_coherent(store) == ([], [])
    assert coherence.changes(store) == []
    kept = store.execute("SELECT v.failure_class, v.power FROM proposals p JOIN verdicts v "
                         "ON v.id = p.state_verdict_id WHERE p.name = 'plan:q3-4b'").fetchone()
    assert kept[0] == reasons.UNDERPOWERED and json.loads(kept[1])["cases"] == 5
    assert ms.revisitable(store, {"cases": {"web": LANE_CASES + 1}})


def test_soh_coherence_schedules_the_retest_an_adopt_limit_still_has(store, lane_cases):
    ms.record(store, ms.Seen(name="org/m", source="t", lane="code", resolved="org/m"))
    pid = store.execute("SELECT id FROM proposals WHERE name = 'org/m'").fetchone()[0]
    transitions._write(store, pid, "org/m", {"outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT,
                                             "until": "", "detail": "code: underpowered", "decided_at": T})
    store.execute("UPDATE proposals SET next_retest_at = NULL")
    store.commit()
    found = coherence.changes(store)
    assert [c["now"] for c in found] == [["declined", "adopt", "limit", ""]]
    assert found[0]["retest_at"] == T + ms.RETEST_AFTER_SECONDS
    before = store.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]
    coherence.apply(store, found)
    assert store.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == before, "a retest is not a verdict"
    assert _held(store, "org/m")["next_retest_at"] == T + ms.RETEST_AFTER_SECONDS
    assert live_audit._terminal_reason_coherent(store) == ([], [])


def test_soh_coherence_leaves_a_spent_screen_limit_to_a_person(store):
    ms.record(store, ms.Seen(name="org/s", source="t", lane="code", resolved="org/s"))
    pid = store.execute("SELECT id FROM proposals WHERE name = 'org/s'").fetchone()[0]
    transitions._write(store, pid, "org/s", {"outcome": "declined", "tier": ms.SCREEN, "reason": reasons.LIMIT,
                                             "until": "", "detail": "x", "decided_at": T})
    store.execute("UPDATE proposals SET next_retest_at = NULL, retest_count = 3")
    store.commit()
    assert [c.get("skipped", "") for c in coherence.changes(store)] == [
        "no repair names this kind; a person decides it"]


def test_the_repair_is_read_only_through_soh_coherence_without_apply(tmp_path, lane_cases, capsys):
    from harness import cli
    db = tmp_path / "s.db"
    conn = ms.connect(db)
    _live_three(conn)
    conn.close()
    assert cli.main(["coherence", "--db", str(db)]) == 0
    assert "3 of 3" in capsys.readouterr().out
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    try:
        assert len(live_audit._terminal_reason_coherent(ro)[0]) == 3
    finally:
        ro.close()
