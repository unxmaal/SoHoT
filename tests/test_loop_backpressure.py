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
                  detail=f"not screened: needs {need} GB but only 1{i}.4 GB is safely available",
                  until=f"room_gb:>{need}")
    conn.close()


def test_the_streak_counts_one_need_only(tmp_path, monkeypatch):
    from harness import memory_store as ms, reasons
    _seed(tmp_path, monkeypatch, ["org/photo"], deferrals=2, need="20.0")
    conn = ms.connect()
    for i in range(3):
        ms.decide(conn, "org/photo", "queued", tier=ms.SCREEN, reason=reasons.MEMORY,
                  detail=f"not screened: needs 26.5 GB but only 1{i}.4 GB is safely available",
                  until="room_gb:>26.5")
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
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: 26.5)
    before = _verdicts("org/photo")
    cli._report_screen(argparse.Namespace(lane="", top=3, limit=3, run=True, json=False))
    assert _verdicts("org/photo") - before == wrote


def _refusal_row(conn, why, until):
    from harness import memory_store as ms, reasons
    ms.decide(conn, "org/photo", "queued", tier=ms.SCREEN, reason=reasons.MEMORY, detail=f"not screened: {why}", until=until)


def test_a_real_held_back_refusal_counts_in_the_streak(tmp_path, monkeypatch):
    """held_back says GiB, fits says GB; the streak reads the until both write, not the prose. #2148."""
    from harness import memory, memory_store as ms
    _seed(tmp_path, monkeypatch, ["org/photo"], deferrals=0, need="0")
    monkeypatch.setattr(memory, "standing_gb", lambda: 23.2)
    why = memory.held_back(48.1)
    assert "GiB" in why
    conn = ms.connect()
    for night in range(2):
        _refusal_row(conn, why + f" (night {night})", "room_gb:>48.1")
    assert screen_cmd.memory_deferrals(conn, "org/photo") == (2, "48.1")
    conn.close()


def test_an_unrelated_refusal_does_not_count_in_the_streak(tmp_path, monkeypatch):
    from harness import memory, memory_store as ms
    _seed(tmp_path, monkeypatch, ["org/photo"], deferrals=0, need="0")
    monkeypatch.setattr(memory, "standing_gb", lambda: 23.2)
    conn = ms.connect()
    _refusal_row(conn, memory.held_back(48.1), "room_gb:>48.1")
    _refusal_row(conn, "needs 48.1 GiB but the disk is full", "")
    assert screen_cmd.memory_deferrals(conn, "org/photo") == (0, "")
    conn.close()


def test_wait_need_reads_only_what_wait_for_writes():
    from harness import memory
    assert memory.wait_need("room_gb:>26.5") == "26.5"
    assert [memory.wait_need(u) for u in ("", "memory_gb:>26.5", "room_gb:>x", "room_gb:>")] == [""] * 4
