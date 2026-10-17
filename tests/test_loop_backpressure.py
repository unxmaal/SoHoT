"""The loop fetches only when the screen has room for more. #396."""
import argparse

import pytest

from harness.commands import discover as discover_cmd
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from harness import cli, disk


def _ready(name):
    return {"name": name, "state": "ready", "candidate": f"x:{name}"}


def test_the_backlog_counts_only_what_the_screen_could_take_now():
    plan = [_ready("a"), _ready("too-big"),
            {"name": "w", "state": "waiting-on-fetch", "candidate": ""}]
    got = cli.screenable_backlog(plan=plan, room=lambda r: r["name"] != "too-big")
    assert got == ["a"]


def _loop(monkeypatch, backlog):
    fetched = []
    monkeypatch.setattr(disk, "sweep", lambda *a, **k: {})
    monkeypatch.setattr(loop_cmd, "_reopen_retests", lambda *a, **k: [])
    monkeypatch.setattr(loop_cmd, "_reverify", lambda *a, **k: {})
    monkeypatch.setattr(loop_cmd, "_sweeps", lambda *a, **k: {})
    monkeypatch.setattr(screen_cmd, "screenable_backlog", lambda want="": backlog)
    monkeypatch.setattr(screen_cmd, "cmd_fetch", lambda a: fetched.append(a) or 0)
    monkeypatch.setattr(discover_cmd, "cmd_discover", lambda a: 0)
    monkeypatch.setattr(measure_cmd, "measurable", lambda store, top, want="": [])
    monkeypatch.setattr(measure_cmd, "resume_first", lambda store, fresh, want="": fresh)
    monkeypatch.setattr("harness.memory_store.connect",
                        lambda *a, **k: type("S", (), {"close": lambda s: None})())
    cli._loop_spend(argparse.Namespace(top=3, budget_gib=40, lane=""), 0)
    return fetched


def test_a_full_backlog_skips_the_fetch(monkeypatch, capsys):
    """469 GiB sat unscreened because every loop fetched its whole budget."""
    assert _loop(monkeypatch, ["a", "b", "c"]) == []
    assert "already on disk wait for a screen" in capsys.readouterr().out


def test_a_short_backlog_still_fetches(monkeypatch):
    """Negative control: backpressure must not stop discovery."""
    assert len(_loop(monkeypatch, ["a"])) == 1


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


def test_a_memory_deferred_candidate_is_not_backlog(tmp_path, monkeypatch):
    """It fit at fetch time and was deferred at the screen every night. #910."""
    _seed(tmp_path, monkeypatch, ["org/photo", "org/other"])
    plan = [_ready("org/photo"), _ready("org/other")]
    assert cli.screenable_backlog(plan=plan, room=lambda r: True) == ["org/other"]


def test_a_memory_deferral_followed_by_another_verdict_is_backlog_again(tmp_path, monkeypatch):
    """Negative control: only the latest verdict being a memory deferral holds it out."""
    from harness import memory_store as ms
    _seed(tmp_path, monkeypatch, ["org/photo"])
    conn = ms.connect()
    ms.decide(conn, "org/photo", "queued", tier=ms.FETCH, detail="refetched")
    conn.close()
    assert cli.screenable_backlog(plan=[_ready("org/photo")], room=lambda r: True) == ["org/photo"]


def test_the_streak_counts_one_need_only(tmp_path, monkeypatch):
    from harness import memory_store as ms, reasons
    _seed(tmp_path, monkeypatch, ["org/photo"], deferrals=2, need="20.0")
    conn = ms.connect()
    for i in range(3):
        ms.decide(conn, "org/photo", "queued", tier=ms.SCREEN, reason=reasons.MEMORY,
                  detail=f"not screened: needs 26.5 GB but only 1{i}.4 GB is safely available")
    assert screen_cmd.memory_deferrals(conn, "org/photo") == (3, "26.5")
    conn.close()


@pytest.mark.parametrize("top", [1, 3])
def test_a_memory_deferred_leftover_lets_the_ranked_ones_fetch_and_screen(tmp_path, monkeypatch, top):
    """Photoroom held the fetch and a screen slot every night while the rank head was never fetched. #910."""
    import subprocess
    from harness import memory, screen
    ranked = ["org/a", "org/b", "org/c"]
    _seed(tmp_path, monkeypatch, ["org/photo", *ranked])
    plan = [_ready("org/photo")] + [{"name": n, "state": screen.WAITING, "candidate": n,
                                     "modality": "code", "why_not": ""} for n in ranked]
    tight = []

    def fetch(a):
        for r in plan:
            r.update(state=screen.READY, candidate=r["name"], modality="code")
        tight.append(True)
        return 0

    monkeypatch.setattr(disk, "sweep", lambda *a, **k: {})
    monkeypatch.setattr(loop_cmd, "_reopen_retests", lambda *a, **k: [])
    monkeypatch.setattr(loop_cmd, "_reverify", lambda *a, **k: {})
    monkeypatch.setattr(loop_cmd, "_sweeps", lambda *a, **k: {})
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: [dict(r) for r in plan])
    monkeypatch.setattr(screen_cmd, "cmd_fetch", fetch)
    monkeypatch.setattr(memory, "check_model", lambda name, **k: (
        (False, _TIGHT) if tight and name == "org/photo" else (True, "")))
    monkeypatch.setattr(memory, "available_gb", lambda: 31.4)
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (
        argv[0] == "screen" and ran.append(argv[-1])) or type("D", (), {"returncode": 0, "stderr": ""})())
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {"summary": {"x": {"passed": 1}}})
    monkeypatch.setattr(measure_cmd, "measurable", lambda store, top, want="": [])
    cli._loop_spend(argparse.Namespace(top=top, budget_gib=40, lane=""), 0)
    assert tight and ran == ranked[:top]


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
