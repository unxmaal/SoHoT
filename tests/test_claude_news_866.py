"""#866: `soh claude-news` digests only changelog entries newer than the last version seen."""
import json
import subprocess
from argparse import Namespace

import pytest

from harness import claude_news as cn
from harness import delegate
from harness import memory_store as ms
from harness.commands import claude_news as cmd
from harness.commands import common

CHANGELOG = """# Changelog

## 2.1.302

- Added PreCompact and PostCompact hook events
- Improved startup time on large repos

## 2.1.301

* Fixed statusLine rate_limits field missing on resume
- Changed theme colors

## 2.1.300

- Added bashOutputMaxChars setting
- Old fix nobody should see again

## 2.1.299

- Ancient entry
"""

SETTINGS = {"hooks": {"PreToolUse": [], "Stop": []}, "statusLine": {"type": "command"},
            "enabledPlugins": {"gauntlet@local": True, "off@x": False}, "model": "opus"}


class Runner:
    """Fake subprocess.run: `claude --version` answers, osascript is recorded."""

    def __init__(self, version="2.1.299 (Claude Code)"):
        self.version, self.calls = version, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        out = self.version if argv[0] == "claude" else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    @property
    def notifications(self):
        return [c for c in self.calls if c[0] == "osascript"]


def fake_model(text, context):
    assert "hook events in use: PreToolUse, Stop" in context
    return "hook" in text.lower() or "statusline" in text.lower()


@pytest.fixture
def files(tmp_path):
    log = tmp_path / "CHANGELOG.md"
    log.write_text(CHANGELOG, encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
    return log, settings


def run(files, runner, model=fake_model, as_json=True, **over):
    log, settings = files
    a = Namespace(changelog=str(log), settings=str(settings), since="", no_record=False, notify=True)
    for k, v in over.items():
        setattr(a, k, v)
    common._JSON = as_json
    try:
        return cmd.cmd_claude_news(a, model=model, run=runner)
    finally:
        common._JSON = False


def record(version):
    conn = ms.connect()
    try:
        cn.record(conn, version)
    finally:
        conn.close()


def test_two_new_versions_name_only_their_entries(files, capsys):
    record("2.1.300")
    runner = Runner()
    assert run(files, runner) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["versions"] == ["2.1.302", "2.1.301"]
    names = [e["text"] for e in out["relevant"] + out["other"]]
    assert sorted(names) == sorted(["Added PreCompact and PostCompact hook events",
                                    "Improved startup time on large repos",
                                    "Fixed statusLine rate_limits field missing on resume",
                                    "Changed theme colors"])
    assert [e["text"] for e in out["relevant"]] == ["Added PreCompact and PostCompact hook events",
                                                     "Fixed statusLine rate_limits field missing on resume"]
    assert out["classifier"] == "local decide model"
    assert len(runner.notifications) == 1
    conn = ms.connect()
    try:
        assert cn.last_seen(conn) == "2.1.302"
    finally:
        conn.close()


def test_text_puts_relevant_first(files, capsys):
    record("2.1.300")
    assert run(files, Runner(), as_json=False, notify=False) == 0
    out = capsys.readouterr().out
    assert out.index("Relevant to how we run (2)") < out.index("PreCompact") < out.index("The rest (2)") \
        < out.index("Changed theme colors")
    assert "bashOutputMaxChars" not in out


def test_rerun_with_nothing_new_produces_nothing_and_no_notification(files, capsys):
    record("2.1.300")
    run(files, Runner())
    capsys.readouterr()
    runner = Runner()
    assert run(files, runner, as_json=False) == 0
    got = capsys.readouterr()
    assert got.out == ""
    assert runner.notifications == []


def test_nothing_relevant_sends_no_notification(files, capsys):
    record("2.1.300")
    runner = Runner()
    run(files, runner, model=lambda text, context: False)
    assert json.loads(capsys.readouterr().out)["relevant"] == []
    assert runner.notifications == []


def test_first_run_starts_from_the_installed_version(files, capsys):
    run(files, Runner(version="2.1.301 (Claude Code)"))
    out = json.loads(capsys.readouterr().out)
    assert out["since"] == "2.1.301" and out["versions"] == ["2.1.302"]


def test_busy_model_falls_back_to_keywords_and_says_so(files, capsys):
    record("2.1.300")

    def refuses(text, context):
        raise delegate.Refused("a batch run holds the machine: infovore")

    run(files, Runner(), model=refuses)
    out = json.loads(capsys.readouterr().out)
    assert out["classifier"].startswith("keyword match against the setup (local model unavailable: "
                                        "a batch run holds the machine")
    relevant = [e["text"] for e in out["relevant"]]
    assert "Added PreCompact and PostCompact hook events" in relevant
    assert "Fixed statusLine rate_limits field missing on resume" in relevant
    assert "Changed theme colors" not in relevant


def test_model_failing_midway_keeps_earlier_answers(files):
    s = cn.setup(files[1], "2.1.300")
    entries = cn.newer(cn.parse(CHANGELOG), "2.1.300")
    seen = []

    def flaky(text, context):
        seen.append(text)
        if len(seen) > 1:
            raise RuntimeError("gateway down")
        return False

    flags, how = cn.classify(entries, s, flaky)
    assert flags[0] is False and flags[2] is True and len(flags) == len(entries)
    assert "gateway down" in how


def test_no_record_leaves_the_baseline(files, capsys):
    record("2.1.300")
    run(files, Runner(), no_record=True)
    conn = ms.connect()
    try:
        assert cn.last_seen(conn) == "2.1.300"
    finally:
        conn.close()


def test_setup_reads_keys_hooks_and_enabled_plugins(files):
    s = cn.setup(files[1], "2.1.300")
    assert s["hook_events"] == ["PreToolUse", "Stop"]
    assert s["plugins"] == ["gauntlet@local"]
    assert "statusLine" in s["settings_keys"]


def test_local_model_asks_the_decide_lane(monkeypatch):
    got = {}

    def decide(question, schema, context=""):
        got.update(question=question, schema=schema, context=context)
        return {"answers": {"relevant": True}}

    monkeypatch.setattr(delegate, "decide", decide)
    assert cn.local_model("Added X", "ctx") is True
    assert got["question"].endswith("Added X") and got["context"] == "ctx"
    delegate.check_schema(got["schema"])


@pytest.mark.parametrize("answer,want", [("false", False), ("true", True), (False, False), (True, True)])
def test_a_string_false_from_the_decide_lane_is_not_relevant(monkeypatch, answer, want):
    monkeypatch.setattr(delegate, "decide", lambda q, schema, context="": {"answers": {"relevant": answer}})
    assert cn.local_model("Added X", "ctx") is want
