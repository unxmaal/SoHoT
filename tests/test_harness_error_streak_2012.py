"""#2012: a harness_error that never clears is declined at screen_harness_errors and paged, not requeued every night."""
import argparse
import subprocess

import pytest

from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from harness import cli, knobs, memory, monitor, reasons, screen
from harness import memory_store as ms

NAME = "OpenMOSS-Team/MOSS-TTS-v1.5"


class _Done:
    returncode = 0
    stderr = ""


@pytest.fixture
def screened(monkeypatch):
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=NAME, source="t", kind="weights", lane="tts", why="seeded"))
    conn.close()
    plan = [{"name": NAME, "state": screen.READY, "candidate": NAME, "modality": "tts", "why_not": ""}]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(screen_cmd, "_release", lambda store, r: None)
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Done())
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {"summary": {"x": {"passed": 0}}})
    alerts = []
    monkeypatch.setattr(monitor, "alert", lambda kind, environ=None, **k: alerts.append((kind, dict(environ))))

    def once(outcome=screen.decide_class(reasons.HARNESS_ERROR, "long-clause: tts failed")):
        monkeypatch.setattr(screen, "outcome", lambda *a, **k: outcome)
        cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True, json=False))
        conn = ms.connect()
        try:
            got = dict(conn.execute("SELECT v.* FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                                    "WHERE p.name = ? ORDER BY v.id DESC LIMIT 1", (NAME,)).fetchone())
            # Each night's inspect answers between two screens, as the loop's does.
            if got["outcome"] == "queued":
                ms.decide(conn, NAME, "queued", tier="inspect", detail="fits", reason=reasons.CANDIDATE)
            return got
        finally:
            conn.close()
    return once, alerts


def test_the_third_harness_error_in_a_row_is_declined_at_its_limit_and_paged(screened):
    once, alerts = screened
    assert [once()["outcome"] for _ in range(2)] == ["queued", "queued"] and alerts == []
    got = once()
    assert (got["outcome"], got["tier"], got["reason"], got["failure_class"]) == (
        "declined", ms.SCREEN, reasons.LIMIT, reasons.HARNESS_ERROR)
    assert got["until"] == f"limit:screen_harness_errors>{screen_cmd.HARNESS_ERRORS}"
    assert "3 screens in a row" in got["detail"] and "tts failed" in got["detail"]
    assert [(k, e["MONIT_SERVICE"]) for k, e in alerts] == [("service", "screen")]
    assert ms.until_met(got["until"], {"limits": {"screen_harness_errors": 5}})
    assert not ms.until_met(got["until"], {"limits": knobs.limits()})


def test_another_screen_outcome_between_harness_errors_starts_the_count_again(screened):
    once, alerts = screened
    once()
    once()
    once(screen.decide_class(reasons.SERVER_DEAD))
    once()
    assert once()["outcome"] == "queued" and alerts == []
