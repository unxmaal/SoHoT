"""A dead model server stops the screen instead of poisoning the rest. #404."""
import argparse
import subprocess

from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from harness import cli, memory, reasons, screen
from harness import memory_store as ms


class _Done:
    returncode = 0
    stderr = ""


def _setup(monkeypatch, tmp_path, outcome):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    for n in ("org/first", "org/second"):
        ms.record(conn, ms.Seen(name=n, source="t", kind="weights", lane="code",
                                why="seeded"))
    conn.close()
    plan = [{"name": n, "state": screen.READY, "candidate": n, "modality": "code",
             "why_not": ""} for n in ("org/first", "org/second")]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    ran = []
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: (argv[0] == "screen" and ran.append(argv[-1])) or _Done())
    monkeypatch.setattr(measure_cmd, "_receipt_at",
                        lambda out: {"summary": {"x": {"passed": 0}}})
    monkeypatch.setattr(screen, "outcome", lambda *a, **k: outcome)
    return ran


def test_a_dead_server_stops_the_screen(monkeypatch, tmp_path):
    dead = screen.decide_class(reasons.SERVER_DEAD)
    ran = _setup(monkeypatch, tmp_path, dead)
    rc = cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True,
                                               json=False))
    assert ran == ["org/first"] and rc == 1
    conn = ms.connect()
    try:
        assert ms.latest(conn, "org/first")["outcome"] == "queued"
        assert ms.latest(conn, "org/second") is None
    finally:
        conn.close()


def test_an_ordinary_failure_does_not_stop_the_screen(monkeypatch, tmp_path):
    """Negative control."""
    ran = _setup(monkeypatch, tmp_path,
                 screen.decide_class(reasons.CONTENT_FAILED))
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True,
                                          json=False))
    assert ran == ["org/first", "org/second"]


def test_generation_thread_died_is_the_harnesss_fault():
    cls = reasons.classify('HTTP 404: {"error": "generation thread died"}')
    assert cls == reasons.SERVER_DEAD and cls in reasons.STOPS
    assert screen.decide_class(cls).reason == "harness"
