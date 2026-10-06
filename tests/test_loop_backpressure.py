"""The loop fetches only when the screen has room for more. #396."""
import argparse

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
    monkeypatch.setattr(cli, "screenable_backlog", lambda want="": backlog)
    monkeypatch.setattr(cli, "cmd_fetch", lambda a: fetched.append(a) or 0)
    monkeypatch.setattr(cli, "cmd_discover", lambda a: 0)
    monkeypatch.setattr(cli, "measurable", lambda store, top, want="": [])
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
