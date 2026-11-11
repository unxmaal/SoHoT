"""#1749: the revisitable audit fails only a row the loop's requeue recorded as met; one met only since warns."""
import pytest

from harness import heartbeat, holdout, live_audit, reasons
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from harness.memory_store import transitions

T = 1791000000.0
PLAN = "plan:Ornith-1.5-35B-Q4_K_M"


@pytest.fixture
def lane(monkeypatch):
    monkeypatch.setattr(holdout, "for_lane", lambda name, *a, **k: holdout.Split(
        name, tuple(f"d{i}" for i in range(643)), (), False))


def _declined(name, until=PLAN) -> int:
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=name, source="t", lane="code", resolved=name))
    ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T)
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    transitions._write(conn, pid, name, {"outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT,
                                         "until": until, "detail": "code: not planned", "decided_at": T})
    conn.commit()
    vid = conn.execute("SELECT state_verdict_id FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
    conn.close()
    return vid


def _swept(**noted):
    heartbeat.start()
    heartbeat.mark(heartbeat.REOPENED_REVISITABLE, T + 60)
    for key, value in noted.items():
        heartbeat.note(key, value)
    heartbeat.finish(0)


def _revisitable(planned):
    conn = ms.connect()
    try:
        return live_audit._revisitable(conn, {"planned": planned})
    finally:
        conn.close()


def test_a_plan_until_met_only_after_the_requeue_warns(lane):
    _declined("t-evoteam:llamacpp:Ornith-1.5-35B-Q4_K_M")
    _swept(**{heartbeat.REVISIT_MET: [], heartbeat.REVISIT_CASES: {"code": 643}})
    fails, warns = _revisitable(("Ornith-1.5-35B-Q4_K_M",))
    assert fails == [] and "Ornith-1.5-35B-Q4_K_M" in " ".join(warns)


def test_a_plan_until_with_no_met_record_warns(lane):
    _declined("t-evoteam:llamacpp:Ornith-1.5-35B-Q4_K_M")
    _swept(**{heartbeat.REVISIT_CASES: {"code": 643}})
    fails, warns = _revisitable(("Ornith-1.5-35B-Q4_K_M",))
    assert fails == [] and len(warns) == 1


def test_a_row_the_requeue_recorded_as_met_and_left_fails(lane):
    vid = _declined("t-evoteam:llamacpp:Ornith-1.5-35B-Q4_K_M")
    _swept(**{heartbeat.REVISIT_MET: [vid]})
    fails, warns = _revisitable(("Ornith-1.5-35B-Q4_K_M",))
    assert len(fails) == 1 and warns == []


def test_a_limit_until_with_no_met_record_still_fails(lane, monkeypatch):
    _declined("Photoroom/prxpixel-t2i", "limit:steps>1")
    _swept()
    monkeypatch.setattr(reasons, "limits", lambda: {"steps": 8})
    fails, _ = _revisitable(())
    assert len(fails) == 1


def test_the_loop_requeue_records_the_verdicts_it_found_met_and_the_next_loop_keeps_them(lane, monkeypatch):
    met = _declined("org/met", "cases:code>3")
    _declined("org/unmet", "cases:code>9999")
    heartbeat.start()
    loop_cmd._reopen_revisitable()
    heartbeat.finish(0)
    heartbeat.start()
    assert heartbeat.read()[heartbeat.REVISIT_MET] == [met]
