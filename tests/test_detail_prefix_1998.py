"""#1998: met-until reopens, comparison counts and verdict lanes are read from columns, never a detail's prefix."""
import json

import pytest

from harness import adopt, coherence, effects, family, holdout, reasons, screen
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from harness.memory_store import revisit, transitions

T = 1791000000.0
SVG = "cases:svg>3"
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
def conn():
    c = ms.connect()
    yield c
    c.close()


def _pid(conn, name, lane):
    got = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()
    if got is None:
        ms.record(conn, ms.Seen(name=name, source="t", lane=lane, resolved=name))
        ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T - 60)
        got = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()
    return got[0]


def _declined(conn, name, until, *, tier=ms.ADOPT, lane="svg", detail="svg: declined", at=T, **fields):
    pid = _pid(conn, name, lane)
    vid = transitions._write(conn, pid, name, {"outcome": "declined", "tier": tier, "reason": reasons.LIMIT,
                                               "until": until, "detail": detail, "decided_at": at, **fields})
    conn.commit()
    return vid


def _reword_retractions(conn):
    conn.execute("UPDATE verdicts SET detail = 'reopened: worded by a later release' WHERE reopen_kind = 'retraction'")
    conn.commit()


def test_a_met_until_reopened_once_stays_spent_when_its_retraction_is_reworded(conn):
    facts = {"packages": {"diffusers-cuda": ("ftfy",)}}
    _declined(conn, "Photoroom/prxpixel-t2i", "package:ftfy@diffusers-cuda", lane="image", tier=ms.SCREEN)
    assert ms.requeue_revisitable(conn, facts) == ["Photoroom/prxpixel-t2i"]
    _declined(conn, "Photoroom/prxpixel-t2i", "package:ftfy@diffusers-cuda", lane="image", tier=ms.SCREEN,
              detail="ftfy still missing", at=T + 60)
    _reword_retractions(conn)
    assert ms.revisitable(conn, facts) == []
    assert [r["name"] for r in ms.revisitable(conn, facts, spent=True)] == ["Photoroom/prxpixel-t2i"]


def test_a_retraction_that_only_says_is_met_spends_nothing(conn):
    facts = {"packages": {"diffusers-cuda": ("ftfy",)}}
    _declined(conn, "org/m", "package:ftfy@diffusers-cuda", lane="image", tier=ms.SCREEN)
    transitions.retract(conn, "org/m", "package:ftfy@diffusers-cuda is met by a person's hand")
    _declined(conn, "org/m", "package:ftfy@diffusers-cuda", lane="image", tier=ms.SCREEN, at=T + 60)
    assert [r["name"] for r in ms.revisitable(conn, facts)] == ["org/m"]


def test_an_upstream_commit_reopen_is_a_met_until(conn):
    ms.record(conn, ms.Seen(name="org/u", source="t", lane="code", resolved="org/u"))
    ms.decide(conn, "org/u", "declined", tier=ms.INSPECT, reason=reasons.UPSTREAM,
              until="commit_after:2026-01-01T00:00:00Z", detail="dead: no commit since 2026-01-01")
    got = ms.requeue_upstream_committed(conn, lambda repo, registry: "2026-02-01T00:00:00Z")
    assert [r["name"] for r in got["committed"]] == ["org/u"]
    assert conn.execute("SELECT event FROM verdicts WHERE reopen_kind = 'retraction'").fetchone()[0] == revisit.UNTIL_MET


def test_an_inspect_reopen_past_its_screen_is_moved_when_its_retraction_is_reworded(conn, grown):
    _declined(conn, "OmniSVG/OmniSVG1.1_8B", SVG)
    transitions.retract(conn, "OmniSVG/OmniSVG1.1_8B", f"{SVG} is met here", event=revisit.UNTIL_MET)
    _reword_retractions(conn)
    assert [r["name"] for r in ms.reopened_too_far(conn)] == ["OmniSVG/OmniSVG1.1_8B"]
    assert ms.requeue_reopened_too_far(conn) == ["OmniSVG/OmniSVG1.1_8B"]
    assert conn.execute("SELECT event FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()[0] == revisit.UNTIL_MET


def test_an_inspect_retraction_that_only_says_is_met_is_not_moved(conn, grown):
    _declined(conn, "OmniSVG/OmniSVG1.1_8B", SVG)
    transitions.retract(conn, "OmniSVG/OmniSVG1.1_8B", f"{SVG} is met here")
    assert ms.reopened_too_far(conn) == []


def test_a_held_adopt_row_with_no_lane_is_given_none_by_its_detail(conn, grown):
    pid = _pid(conn, "OmniSVG/OmniSVG1.1_8B", "")
    vid = transitions._write(conn, pid, "OmniSVG/OmniSVG1.1_8B", {
        "outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT, "until": f"cases:svg>{GROWN}",
        "detail": "svg: underpowered", "decided_at": T, "failure_class": reasons.LANE_TOO_SMALL})
    conn.execute("UPDATE verdicts SET power = ?, split_version = '1' WHERE id = ?", (json.dumps(SATURATED), vid))
    conn.commit()
    assert coherence.past_growth(conn) == []
    conn.execute("UPDATE verdicts SET lane = 'svg', detail = 'underpowered, worded anew' WHERE id = ?", (vid,))
    assert [c["now"][3] for c in coherence.past_growth(conn)] == ["cases:svg>3"]


def test_a_held_adopt_limit_with_no_lane_waits_on_no_lane_its_detail_names(conn, grown):
    pid = _pid(conn, "org/l", "")
    vid = transitions._write(conn, pid, "org/l", {
        "outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT, "until": "",
        "detail": "svg: underpowered", "decided_at": T, "failure_class": reasons.UNDERPOWERED})
    conn.execute("UPDATE verdicts SET power = ?, split_version = '1' WHERE id = ?", (json.dumps(SATURATED), vid))
    conn.commit()
    assert coherence.lane_bound(conn) == []
    assert not [c for c in coherence.changes(conn) if "svg" in json.dumps(c.get("now", ""))]
    conn.execute("UPDATE verdicts SET lane = 'svg', detail = 'underpowered, worded anew' WHERE id = ?", (vid,))
    assert [c["now"][3] for c in coherence.lane_bound(conn)] == ["cases:svg>3"]


def test_a_spent_adopt_limit_with_no_lane_waits_on_no_lane_its_detail_names(conn, grown):
    pid = _pid(conn, "plan:q3-4b", "")
    plan = {"cases": 5, "cases_needed": None, "side": "holdout", "power": 0.63}
    for said in ("svg: underpowered", "svg: underpowered again"):
        vid = transitions._write(conn, pid, "plan:q3-4b", {
            "outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT, "until": "", "detail": said,
            "decided_at": T, "failure_class": reasons.UNDERPOWERED})
        conn.execute("UPDATE verdicts SET power = ?, split_version = '1' WHERE id = ?", (json.dumps(plan), vid))
    conn.commit()
    assert [c.get("skipped") for c in coherence.changes(conn)] == ["no repair names this kind; a person decides it"]
    conn.execute("UPDATE verdicts SET lane = 'svg', detail = 'underpowered, worded anew' WHERE id = ?", (vid,))
    found = coherence.changes(conn)
    assert [c["now"][3] for c in found] == ["cases:svg>5"]
    [new] = coherence.apply(conn, found)
    assert conn.execute("SELECT event FROM verdicts WHERE id = ?", (new,)).fetchone()[0] == adopt.REDECIDED


def _adopt_row(conn, name, lane, detail, outcome="declined", reason=reasons.CANDIDATE, **extra):
    pid = _pid(conn, name, "code")
    return transitions._write(conn, pid, name, {"outcome": outcome, "tier": ms.ADOPT, "reason": reason,
                                                "until": "", "detail": detail, "decided_at": T, "lane": lane,
                                                **extra})


def test_effects_replay_takes_the_verdicts_lane_not_its_details_head(conn):
    _adopt_row(conn, "org/e", "svg", "code: worded so its head names another lane")
    conn.commit()
    got = effects.replay(conn, {"svg": 0.3, "code": 0.1})
    assert [(r["lane"], r["noise"]) for r in got] == [("svg", 0.3)]


def test_family_standing_keys_by_the_verdicts_lane_not_its_details_head(conn):
    _adopt_row(conn, "org/f", "svg", "code: worded so its head names another lane")
    conn.commit()
    assert {lane for lane, _ in family.standing(conn).families} == {"svg"}


def test_family_standing_falls_back_to_the_proposals_lane(conn):
    _adopt_row(conn, "org/f", "", "svg: an older row with no lane")
    conn.commit()
    assert {lane for lane, _ in family.standing(conn).families} == {"code"}


def test_a_confirmation_job_takes_the_verdicts_lane_not_its_details_head(conn, monkeypatch, capsys):
    power = {"confirm": {"incumbent": "inc/a", "challenger": "org/c", "served": "inc/a"}}
    vid = _adopt_row(conn, "org/c", "svg", "code: worded so its head names another lane", outcome="screened",
                     reason="", failure_class=reasons.CONFIRMING, power=json.dumps(power))
    conn.commit()
    asked = []
    monkeypatch.setattr(measure_cmd, "_served", lambda lane: asked.append(lane) or "other/x")
    monkeypatch.setattr(screen, "candidate_for", lambda lane, spec: None)
    assert measure_cmd._confirm_job(vid) == 0
    assert asked == ["svg"]
    assert "the svg lane no longer serves inc/a" in capsys.readouterr().out


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/memory_store/migrations/v107.py:data:verdicts")
def test_the_backfill_lifts_each_older_met_until_retraction_once(conn):
    from harness.memory_store.migrations import v107
    pid = _pid(conn, "org/b", "image")
    held = conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, until, detail, decided_at) "
                        "VALUES (?, 'declined', 'screen', 'package:ftfy@cuda', 'ftfy missing', 0)", (pid,)).lastrowid
    bare = conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, until, detail, decided_at) "
                        "VALUES (?, 'declined', 'screen', '', 'no until', 0)", (pid,)).lastrowid
    rows = [(held, "retracted: package:ftfy@cuda is met here", ""),
            (held, "retracted: package:ftfy@cuda is met: the upstream last committed 2026-01-01", ""),
            (held, "retracted: package:ftfy@cuda is met and its screen passed: reopened to screened", ""),
            (held, "retracted: package:other@cuda is met here", ""),
            (held, "retracted: a parent's download ranking retired it", ""),
            (None, "retracted: package:ftfy@cuda is met here", ""),
            (bare, "retracted:  is met here", ""),
            (held, "retracted: package:ftfy@cuda is met here", "kept")]
    ids = [conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, reopens, reopen_kind, event, "
                        "decided_at) VALUES (?, 'queued', 'inspect', ?, ?, 'retraction', ?, 1)",
                        (pid, said, reopens, event)).lastrowid for reopens, said, event in rows]
    v107.data(conn)
    v107.data(conn)
    got = [conn.execute("SELECT event FROM verdicts WHERE id = ?", (i,)).fetchone()[0] for i in ids]
    assert got == [revisit.UNTIL_MET, revisit.UNTIL_MET, revisit.UNTIL_MET, "", "", "", "", "kept"]
    said = {"code: re-decided (#1053): cases:code>9 counted the lane after it grew; code: x": ("", ""),
            "re-decided (#1001): reason limit with no until and no retest; no retest is left": ("", ""),
            "code: re-decided (#1452): lane too small": ("kept", ""),
            "retracted: re-decided (#991): its why": ("", "retraction"),
            "code: lost on the holdout": ("", "")}
    ids = [conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, event, reopen_kind, decided_at) "
                        "VALUES (?, 'declined', 'adopt', ?, ?, ?, 2)", (pid, d, e, k)).lastrowid
           for d, (e, k) in said.items()]
    v107.data(conn)
    got = [conn.execute("SELECT event FROM verdicts WHERE id = ?", (i,)).fetchone()[0] for i in ids]
    assert got == [adopt.REDECIDED, adopt.REDECIDED, "kept", "", ""]
