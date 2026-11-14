"""A screen memory deferral spends no slot and stops writing a verdict for one need. #910."""
import argparse

import pytest

from harness.commands import discover as discover_cmd
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from harness import cli, disk


def _ready(name):
    return {"name": name, "state": "ready", "candidate": f"x:{name}"}




_TIGHT = ("needs 26.5 GB but only 13.4 GB is safely available (31.4 GB free, "
          "77.8 GB GPU ceiling, 18.0 GB reserved for the system)")


def _seed(tmp_path, monkeypatch, names, deferrals=1, need="26.5"):
    from harness import memory_store as ms, reasons
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    for n in names:
        ms.record(conn, ms.Seen(name=n, source="t", kind="weights", lane="code", why="seeded"))
    for i in range(deferrals):
        ms.decide(conn, "org/photo", "queued", tier=ms.SCREEN, reason=reasons.MEMORY,
                  detail=f"not screened: needs {need} GB but only 1{i}.4 GB is safely available")
    conn.close()


def test_the_streak_counts_one_need_only(tmp_path, monkeypatch):
    from harness import memory_store as ms, reasons
    _seed(tmp_path, monkeypatch, ["org/photo"], deferrals=2, need="20.0")
    conn = ms.connect()
    for i in range(3):
        ms.decide(conn, "org/photo", "queued", tier=ms.SCREEN, reason=reasons.MEMORY,
                  detail=f"not screened: needs 26.5 GB but only 1{i}.4 GB is safely available")
    assert screen_cmd.memory_deferrals(conn, "org/photo") == (3, "26.5")
    conn.close()


def _verdicts(name):
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                            "WHERE p.name = ?", (name,)).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.parametrize("deferrals, need, wrote", [(3, "26.5", 0), (2, "26.5", 1), (3, "20.0", 1)])
def test_a_long_same_need_deferral_stops_writing_a_verdict_each_night(tmp_path, monkeypatch,
                                                                       deferrals, need, wrote):
    """Photoroom was requeued for memory 95 times. #910."""
    from harness import memory, screen
    _seed(tmp_path, monkeypatch, ["org/photo"], deferrals=deferrals, need=need)
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: [
        {**_ready("org/photo"), "candidate": "org/photo", "modality": "code", "why_not": ""}])
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (False, _TIGHT))
    monkeypatch.setattr(memory, "available_gb", lambda: 31.4)
    before = _verdicts("org/photo")
    cli._report_screen(argparse.Namespace(lane="", top=3, limit=3, run=True, json=False))
    assert _verdicts("org/photo") - before == wrote
