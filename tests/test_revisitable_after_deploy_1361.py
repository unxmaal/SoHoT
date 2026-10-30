"""#1361: a cases: until met only after the loop's last requeue (a deploy added cases) warns; one met at the requeue fails."""
import pytest

from harness import heartbeat, holdout, live_audit, reasons
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from harness.memory_store import transitions

T = 1791000000.0
SVG = "cases:svg>3"


@pytest.fixture
def lane(monkeypatch):
    size = {"svg": 643}
    monkeypatch.setattr(holdout, "for_lane", lambda name, *a, **k: holdout.Split(
        name, tuple(f"d{i}" for i in range(size.get(name, 1))), (), False))
    return size


def _declined(name, until=SVG):
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=name, source="t", lane="svg", resolved=name))
    ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T)
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    transitions._write(conn, pid, name, {"outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT,
                                         "until": until, "detail": "svg: lane too small", "decided_at": T})
    conn.commit()
    conn.close()


def _swept(**noted):
    heartbeat.start()
    heartbeat.mark(heartbeat.REOPENED_REVISITABLE, T + 60)
    for key, value in noted.items():
        heartbeat.note(key, value)
    heartbeat.finish(0)


def _audit():
    return {c["name"]: c for c in live_audit.audit(ms.db_path())["checks"]}["revisitable"]


def test_a_cases_until_the_requeue_saw_unmet_warns_once_a_deploy_adds_cases(lane):
    _declined("OmniSVG/OmniSVG1.1_4B")
    _swept(**{heartbeat.REVISIT_CASES: {"svg": 3}})
    got = _audit()
    assert got["ok"] and got["warn"] and "OmniSVG/OmniSVG1.1_4B" in got["detail"]


def test_a_cases_until_the_requeue_saw_met_and_left_fails(lane):
    _declined("OmniSVG/OmniSVG1.1_4B")
    _swept(**{heartbeat.REVISIT_CASES: {"svg": 643}})
    got = _audit()
    assert not got["ok"] and "OmniSVG/OmniSVG1.1_4B" in got["detail"]


def test_without_recorded_counts_a_deploy_since_the_sweep_makes_a_cases_until_a_warning(lane, monkeypatch):
    _declined("OmniSVG/OmniSVG1.1_4B")
    monkeypatch.setattr(heartbeat, "code_commit", lambda *a: "a" * 40)
    _swept()
    monkeypatch.setattr(heartbeat, "code_commit", lambda *a: "b" * 40)
    got = _audit()
    assert got["ok"] and got["warn"] and "OmniSVG/OmniSVG1.1_4B" in got["detail"]


def test_a_deploy_never_excuses_an_until_that_is_not_about_cases(lane, monkeypatch):
    _declined("Photoroom/prxpixel-t2i", "limit:steps>1")
    monkeypatch.setattr(heartbeat, "code_commit", lambda *a: "a" * 40)
    _swept()
    monkeypatch.setattr(heartbeat, "code_commit", lambda *a: "b" * 40)
    monkeypatch.setattr(reasons, "limits", lambda: {"steps": 8})
    got = _audit()
    assert not got["ok"] and "Photoroom/prxpixel-t2i" in got["detail"]


def test_the_loop_requeue_records_the_case_counts_it_judged_by_and_the_next_loop_keeps_them(lane):
    _declined("org/unmet", "cases:svg>9999")
    heartbeat.start()
    loop_cmd._reopen_revisitable()
    heartbeat.finish(0)
    heartbeat.start()
    assert heartbeat.read()[heartbeat.REVISIT_CASES] == {"svg": 643}
