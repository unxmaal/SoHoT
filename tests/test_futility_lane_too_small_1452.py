"""#1452: a futility stop on a holdout no repeat could power waits on the lane's cases, as the full gate's null does."""
import dataclasses
import json

import pytest

from harness import adopt, coherence, holdout, live_audit, looks, power, reasons
from harness import memory_store as ms
from harness.memory_store import transitions

T = 1791000000.0
INC, CH = "llamacpp:Inc", "llamacpp:Ch"
SPLIT = holdout.Split("code", tuple(f"d{i}" for i in range(60)), tuple(f"h{i}" for i in range(40)), False)
UNPOWERED = power.Plan(repeat=1, power=0.3, cells=40, cases=40, effect=0.1, alpha=0.05, target=0.8, cap=16,
                       capped=True, stochastic=True, observed=200, why="", cases_needed=300, odds=(0.1, 0.02))
POWERED = dataclasses.replace(UNPOWERED, power=0.6, cases_needed=40)


@pytest.fixture(autouse=True)
def code_lane(monkeypatch):
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: dataclasses.replace(SPLIT, lane=lane))


def _rows(n: int, lost: int) -> list[dict]:
    out = []
    for i, c in enumerate(SPLIT.holdout[:n]):
        out += [{"case_id": c, "candidate": INC, "passed": True, "seconds": 1.0},
                {"case_id": c, "candidate": CH, "passed": i >= lost, "seconds": 1.0}]
    return out


def _look(plan):
    return looks.look(_rows(35, lost=20), lane="code", inc_key=INC, ch_key=CH, split=SPLIT, plan=plan.as_dict(),
                      alpha=0.05, spent_before=0.0, n=2, spec=CH)


def test_an_unpowered_futility_stop_is_lane_too_small_waiting_on_the_lanes_cases():
    look, v = _look(UNPOWERED)
    assert look.decision == "futility" and not v.adopt
    assert v.failure_class == reasons.LANE_TOO_SMALL
    assert v.until == "cases:code>966", "100 lane cases now, 867 more before 40 holdout cases grow to 300"
    assert v.why.startswith("lane too small, needs 300 holdout cases") and "(futility: look 2" in v.why
    assert adopt.outcome_of(v) == ("declined", reasons.LIMIT)


def test_a_powered_futility_stop_stays_a_loss():
    look, v = _look(POWERED)
    assert look.decision == "futility"
    assert (v.failure_class, v.until) == ("", "") and v.why.startswith("futility:")
    assert adopt.outcome_of(v) == ("declined", reasons.CANDIDATE)


def test_the_look_and_the_full_gate_wait_on_the_same_until():
    _, v = _look(UNPOWERED)
    null = adopt.Verdict("code", INC, CH, False, "p=0.40")
    full = adopt._lane_too_small("code", INC, CH, null, UNPOWERED, SPLIT)
    assert (v.failure_class, v.until) == (full.failure_class, full.until)


# --- stored futility verdicts are re-decided through soh coherence ---------------

def _stored(conn, name, plan):
    ms.record(conn, ms.Seen(name=name, source="t", lane="code", resolved=name))
    ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T)
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    vid = transitions._write(conn, pid, name, {
        "outcome": "declined", "tier": ms.ADOPT, "reason": reasons.CANDIDATE, "until": "", "decided_at": T,
        "detail": "code: futility: look 2 at 35/40 holdout cells: 0 gained, 20 lost, conditional power 0.00",
        "failure_class": ""})
    conn.execute("UPDATE verdicts SET power = ?, split_version = '1' WHERE id = ?", (json.dumps(plan), vid))
    conn.commit()


def test_soh_coherence_re_decides_a_stored_unpowered_futility_stop_and_leaves_a_powered_one(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        _stored(conn, "org/unpowered", UNPOWERED.as_dict())
        _stored(conn, "org/powered", POWERED.as_dict())
        found = coherence.changes(conn)
        assert {c["name"]: c["now"] for c in found} == {
            "org/unpowered": ["declined", "adopt", "limit", "cases:code>966"]}
        assert found[0]["detail"].startswith("code: re-decided (#1452): lane too small")
        coherence.apply(conn, found)
        got = conn.execute("SELECT p.name, v.reason, v.until, v.failure_class FROM proposals p "
                           "JOIN verdicts v ON v.id = p.state_verdict_id ORDER BY p.name").fetchall()
        assert [tuple(r) for r in got] == [("org/powered", reasons.CANDIDATE, "", ""),
                                           ("org/unpowered", reasons.LIMIT, "cases:code>966", reasons.LANE_TOO_SMALL)]
        assert coherence.changes(conn) == []
        assert live_audit._terminal_reason_coherent(conn) == ([], [])
    finally:
        conn.close()
