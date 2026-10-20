"""#1060: a met cases/limit until on a decline past its screen reopens to the measure queue; machine facts reopen to inspect."""
import pytest

from harness import heartbeat, holdout, live_audit, methods, reasons
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from harness.memory_store import transitions

T = 1791000000.0
SVG = "cases:svg>3"
MODEL = "OmniSVG/OmniSVG1.1_8B"
METHOD = "best-of:3:q3-30b"


@pytest.fixture
def grown(monkeypatch):
    split = holdout.Split("svg", tuple(f"d{i}" for i in range(448)), tuple(f"h{i}" for i in range(195)), False)
    one = holdout.Split("other", ("o",), ("o",), True)
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: split if lane == "svg" else one)
    return split


def _declined(conn, name, until, *, tier=ms.ADOPT, kind="weights", lane="svg", reason=reasons.LIMIT, at=T):
    if conn.execute("SELECT 1 FROM proposals WHERE name = ?", (name,)).fetchone() is None:
        ms.record(conn, ms.Seen(name=name, source="t", kind=kind, lane=lane, resolved=name))
        ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=at - 60,
                  detail="1 case(s) passed a screen")
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    transitions._write(conn, pid, name, {"outcome": "declined", "tier": tier, "reason": reason, "until": until,
                                         "detail": f"{lane}: declined", "decided_at": at})
    conn.commit()


def _state(conn, name):
    return tuple(conn.execute("SELECT p.state, v.tier, v.reason FROM proposals p "
                              "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone())


def _measured(conn):
    return [r["name"] for r in measure_cmd.resume_first(conn, measure_cmd.measurable(conn, 25))]


def test_a_cases_decline_at_adopt_reopens_to_the_measure_queue_for_a_model_and_a_method(grown):
    conn = ms.connect()
    try:
        _declined(conn, MODEL, SVG)
        _declined(conn, METHOD, SVG, kind=methods.CROSSING_KIND)
        assert sorted(ms.requeue_revisitable(conn, {})) == sorted([METHOD, MODEL])
        assert _state(conn, MODEL) == ("screened", ms.SCREEN, reasons.REOPENED)
        assert _state(conn, METHOD) == ("screened", ms.SCREEN, reasons.REOPENED)
        assert sorted(_measured(conn)) == sorted([METHOD, MODEL])
    finally:
        conn.close()


@pytest.mark.parametrize("until, tier, want", [
    (SVG, ms.ADOPT, ("screened", ms.SCREEN)),
    ("limit:max_tokens.code>4000", ms.ADOPT, ("screened", ms.SCREEN)),
    ("limit:max_tokens.code>4000", ms.MEASURE, ("screened", ms.SCREEN)),
    ("limit:max_tokens.code>4000", ms.SCREEN, ("queued", ms.INSPECT)),
    ("package:ftfy@diffusers-cuda", ms.SCREEN, ("queued", ms.INSPECT)),
    ("package:ftfy@diffusers-cuda", ms.ADOPT, ("queued", ms.INSPECT)),
    ("ceiling_gb:>60", ms.INSPECT, ("queued", ms.INSPECT)),
    ("runtime:llamacpp", ms.ADOPT, ("queued", ms.INSPECT)),
])
def test_each_until_reopens_to_the_tier_it_gates(until, tier, want):
    assert ms.reopens_to(until, tier) == want


def test_a_machine_fact_decline_still_reopens_to_inspect(grown):
    conn = ms.connect()
    try:
        _declined(conn, "Photoroom/prxpixel-t2i", "package:ftfy@diffusers-cuda", tier=ms.SCREEN, lane="image",
                  reason=reasons.RUNTIME)
        assert ms.requeue_revisitable(conn, {"packages": {"diffusers-cuda": ("ftfy",)}}) == ["Photoroom/prxpixel-t2i"]
        assert _state(conn, "Photoroom/prxpixel-t2i") == ("queued", ms.INSPECT, reasons.REOPENED)
        assert _measured(conn) == []
    finally:
        conn.close()


def _reopened_by_old_code(conn, name, until):
    transitions.retract(conn, name, f"{until} is met here")


def test_the_loop_moves_an_old_inspect_reopen_on_to_the_measure_queue_once(grown, capsys):
    conn = ms.connect()
    _declined(conn, MODEL, SVG)
    _declined(conn, METHOD, SVG, kind=methods.CROSSING_KIND)
    _declined(conn, "Photoroom/prxpixel-t2i", "package:ftfy@diffusers-cuda", tier=ms.SCREEN, lane="image",
              reason=reasons.RUNTIME)
    for name, until in ((MODEL, SVG), (METHOD, SVG), ("Photoroom/prxpixel-t2i", "package:ftfy@diffusers-cuda")):
        _reopened_by_old_code(conn, name, until)
    assert [r["name"] for r in ms.reopened_too_far(conn)] == sorted([METHOD, MODEL])
    conn.close()
    heartbeat.start()
    assert loop_cmd._move_past_screen() == sorted([METHOD, MODEL])
    assert f"    {MODEL}" in capsys.readouterr().out
    conn = ms.connect()
    try:
        assert _state(conn, MODEL) == ("screened", ms.SCREEN, reasons.REOPENED)
        assert _state(conn, METHOD) == ("screened", ms.SCREEN, reasons.REOPENED)
        assert _state(conn, "Photoroom/prxpixel-t2i") == ("queued", ms.INSPECT, reasons.REOPENED)
        assert sorted(_measured(conn)) == sorted([METHOD, MODEL])
        assert ms.reopened_too_far(conn) == []
    finally:
        conn.close()
    assert loop_cmd._move_past_screen() == []
    assert heartbeat.marked(heartbeat.MOVED_PAST_SCREEN) is not None


def test_a_reopen_for_another_cause_is_not_moved(grown):
    conn = ms.connect()
    try:
        _declined(conn, MODEL, SVG)
        transitions.retract(conn, MODEL, "a parent's download ranking retired it; inspect reads it on its own")
        assert ms.reopened_too_far(conn) == []
    finally:
        conn.close()


def test_a_reopen_that_inspect_has_since_answered_is_not_moved(grown):
    conn = ms.connect()
    try:
        _declined(conn, MODEL, SVG)
        _reopened_by_old_code(conn, MODEL, SVG)
        ms.decide(conn, MODEL, "queued", tier=ms.INSPECT, reason=reasons.CANDIDATE, detail="fits")
        assert ms.reopened_too_far(conn) == []
    finally:
        conn.close()


def test_the_audit_warns_on_a_stranded_reopen_until_the_loop_moves_it_then_fails(grown):
    conn = ms.connect()
    try:
        _declined(conn, MODEL, SVG)
        _reopened_by_old_code(conn, MODEL, SVG)
        decided = conn.execute("SELECT v.decided_at FROM proposals p JOIN verdicts v "
                               "ON v.id = p.state_verdict_id WHERE p.name = ?", (MODEL,)).fetchone()[0]
        bad, fresh = live_audit._reopened_past_screen(conn, moved_at=None)
        assert bad == [] and len(fresh) == 1 and MODEL in fresh[0]
        bad, fresh = live_audit._reopened_past_screen(conn, moved_at=decided + 1)
        assert len(bad) == 1 and fresh == []
        ms.requeue_reopened_too_far(conn)
        assert live_audit._reopened_past_screen(conn, moved_at=decided + 1) == ([], [])
    finally:
        conn.close()


def test_the_discover_step_runs_the_move_before_the_revisit_requeue():
    import inspect
    src = inspect.getsource(loop_cmd._run_loop_held)
    assert src.index("_move_past_screen") < src.index("_reopen_revisitable") < src.index("cmd_discover(sub)")
