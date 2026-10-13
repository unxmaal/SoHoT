"""Headless claude -p on the gateway: profile, checks, runner and leak check, with no model. #830."""
from __future__ import annotations

import dataclasses
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import headless as hl
from harness import headless

ALIAS = "sohot-agent"
SECRET = "sk-test-not-a-real-key"

GOOD = {
    "log-summary": {"SUMMARY.md": "ERRORS: 8\nTOP: db\nThe database reset connections five times.\n"},
    "status-digest": {"counts.json": '{"200": 23, "404": 6, "500": 3}'},
    "failing-test": {"FAILING.txt": "tests/test_money.py::test_negative_amount\n"},
    "issue-triage": {"labels.json": '["bug", "area:gateway", "priority:high"]'},
    "pr-description": {"PR.md": "# Exponential backoff for retries\n\n## Summary\nAdds backoff_seconds "
                                "and raises MAX_RETRIES from 3 to 5.\n\n## Testing\ntest_retry covers it.\n"},
    "edit-file": "expected",
}
#: The answer a careless reading gives; each must fail its check.
BAD = {
    "log-summary": {"SUMMARY.md": "ERRORS: 12\nTOP: gateway\nErrors happened.\n"},
    "status-digest": {"counts.json": '{"200": 22, "404": 7, "500": 3}'},
    "failing-test": {"FAILING.txt": "tests/test_parse.py::test_failure_message\n"},
    "issue-triage": {"labels.json": '["enhancement", "area:gateway"]'},
    "pr-description": {"PR.md": "Exponential backoff\n\n## Summary\nAdds backoff.\n"},
    "edit-file": {"src/config.js": "const TIMEOUT_MS = 45000;\n", "src/main.js": "loadConfig()\n"},
}


def _workspace(task, tmp_path: Path, answer) -> Path:
    work = tmp_path / task.name
    shutil.copytree(task.root / "files", work)
    if answer == "expected":
        shutil.copytree(task.root / "expected", work, dirs_exist_ok=True)
    else:
        for rel, text in answer.items():
            (work / rel).write_text(text, encoding="utf-8")
    return work


def test_the_set_holds_five_to_eight_recorded_jobs_each_with_a_good_and_bad_answer_here():
    tasks = hl.load()
    assert 5 <= len(tasks) <= 8
    assert {t.name for t in tasks} == set(GOOD) == set(BAD)
    assert len({t.job for t in tasks}) >= 5


@pytest.mark.parametrize("name", sorted(GOOD))
def test_a_right_answer_passes_its_check(name, tmp_path):
    task = hl.load([name])[0]
    passed, whys = hl.grade(task, _workspace(task, tmp_path, GOOD[name]))
    assert passed, whys


@pytest.mark.parametrize("name", sorted(BAD))
def test_the_careless_answer_fails_its_check(name, tmp_path):
    task = hl.load([name])[0]
    passed, whys = hl.grade(task, _workspace(task, tmp_path, BAD[name]))
    assert not passed and whys


@pytest.mark.parametrize("name", sorted(GOOD))
def test_doing_nothing_fails(name, tmp_path):
    task = hl.load([name])[0]
    assert not hl.grade(task, _workspace(task, tmp_path, {}))[0]


def test_triage_refuses_a_label_that_is_not_in_the_list(tmp_path):
    task = hl.load(["issue-triage"])[0]
    work = _workspace(task, tmp_path, {"labels.json": '["bug", "area:gateway", "urgent"]'})
    passed, whys = hl.grade(task, work)
    assert not passed and "not allowed" in whys[0]


def test_triage_refuses_a_second_area_beside_the_right_one(tmp_path):
    task = hl.load(["issue-triage"])[0]
    work = _workspace(task, tmp_path, {"labels.json": '["bug", "area:gateway", "area:ui"]'})
    passed, whys = hl.grade(task, work)
    assert not passed and "wrong ['area:ui']" in whys[0]


def test_an_answer_file_must_hold_only_the_answer(tmp_path):
    task = hl.load(["failing-test"])[0]
    work = _workspace(task, tmp_path, {"FAILING.txt": "Failed: tests/test_money.py::test_negative_amount"})
    assert not hl.grade(task, work)[0]


def test_the_profile_sends_every_tier_to_the_alias_and_nothing_to_anthropic():
    env = headless.profile(ALIAS, "http://127.0.0.1:4000/", SECRET)
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4000"
    for name in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                 "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
                 "CLAUDE_CODE_SUBAGENT_MODEL"):
        assert env[name] == ALIAS, name
    assert env["ANTHROPIC_AUTH_TOKEN"] == env["ANTHROPIC_API_KEY"] == SECRET
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert not any("anthropic.com" in v for v in env.values())


def test_the_child_loses_every_route_around_the_gateway():
    parent = {"PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "oauth", "CLAUDE_CODE_USE_BEDROCK": "1",
              "ANTHROPIC_MODEL": "claude-opus-5-5", "ANTHROPIC_BASE_URL": "https://api.anthropic.com"}
    env = headless.child_env(ALIAS, "http://gw:4000", SECRET, environ=parent)
    assert env["PATH"] == "/bin"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env and "CLAUDE_CODE_USE_BEDROCK" not in env
    assert env["ANTHROPIC_MODEL"] == ALIAS and env["ANTHROPIC_BASE_URL"] == "http://gw:4000"


def test_the_control_uses_its_own_login_not_the_gateway():
    parent = {"ANTHROPIC_BASE_URL": "http://gw:4000", "ANTHROPIC_API_KEY": SECRET,
              "ANTHROPIC_MODEL": ALIAS, "HOME": "/h"}
    env = headless.control_env(environ=parent)
    assert "ANTHROPIC_BASE_URL" not in env and "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_MODEL" not in env and env["HOME"] == "/h"


def test_the_printed_profile_never_holds_the_key():
    text = headless.shell(ALIAS, "http://127.0.0.1:4000")
    assert "KEY\n" not in text and SECRET not in text
    assert 'export ANTHROPIC_AUTH_TOKEN="$(soh gateway key)"' in text
    assert "export CLAUDE_CODE_SUBAGENT_MODEL=sohot-agent" in text


def _stream(turns=3, extra=()):
    lines = [{"type": "system", "subtype": "init"},
             {"type": "assistant", "message": {"id": "m1", "content": [
                 {"type": "tool_use", "name": "Read", "input": {}}]}},
             {"type": "assistant", "message": {"id": "m1", "content": [
                 {"type": "tool_use", "name": "Write", "input": {}}]}},
             {"type": "user", "message": {"content": [
                 {"type": "tool_result", "is_error": True,
                  "content": "<tool_use_error>InputValidationError: file_path is missing</tool_use_error>"},
                 {"type": "tool_result", "is_error": True, "content": "File does not exist."}]}},
             {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "ok"}]}},
             *extra,
             {"type": "result", "subtype": "success", "is_error": False, "num_turns": turns,
              "modelUsage": {ALIAS: {"inputTokens": 10}}}]
    return "\n".join(json.dumps(x) for x in lines) + "\nnot json\n"


def test_the_stream_counts_requests_calls_and_only_malformed_calls_as_invalid():
    got = hl.parse_stream(_stream())
    assert got["api_calls"] == 2 and got["tool_calls"] == 2
    assert got["invalid_calls"] == 1 and got["tool_errors"] == 2
    assert got["result"]["num_turns"] == 3


def _fake(write: dict, stdout: str, seen: list):
    def execute(argv, *, cwd, env, input, timeout, **_kw):
        seen.append(SimpleNamespace(argv=argv, cwd=cwd, env=env, input=input, timeout=timeout))
        for rel, text in write.items():
            (Path(cwd) / rel).write_text(text, encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return execute


def _clock(*ticks):
    it = iter(ticks)
    return lambda: next(it)


def test_a_run_grades_the_workspace_and_records_turns_calls_and_wall(tmp_path):
    task, seen = hl.load(["failing-test"])[0], []
    row = hl.run_task(task, ALIAS, {"X": "1"}, True, execute=_fake(GOOD["failing-test"], _stream(), seen),
                      clock=_clock(100.0, 112.5))
    assert row["passed"] and row["turns"] == 3 and row["tool_calls"] == 2 and row["invalid_calls"] == 1
    assert row["wall_s"] == 12.5 and row["model_usage"] == [ALIAS] and row["limit"] == ""
    call = seen[0]
    assert call.input == task.prompt and task.prompt not in call.argv
    assert "--bare" in call.argv and call.argv[call.argv.index("--model") + 1] == ALIAS
    assert call.env == {"X": "1"}
    assert not (task.root / "files" / "FAILING.txt").exists()


def test_the_control_strips_its_prefix_and_keeps_its_login(tmp_path):
    seen = []
    hl.run_task(hl.load(["failing-test"])[0], "claude:opus", {}, False,
                execute=_fake({}, _stream(), seen), clock=_clock(0.0, 1.0))
    assert "--bare" not in seen[0].argv and seen[0].argv[seen[0].argv.index("--model") + 1] == "opus"


def test_a_timeout_and_a_turn_cap_are_recorded_as_limits_not_failures_of_ability(tmp_path):
    task = hl.load(["failing-test"])[0]

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"], output=b"")
    row = hl.run_task(dataclasses.replace(task, timeout_s=5.0), ALIAS, {}, True, execute=slow,
                      clock=_clock(0.0, 5.0))
    assert row["limit"] == "headless_task_timeout_s>5" and not row["passed"] and row["is_error"]
    capped = _stream().replace('"subtype": "success"', '"subtype": "error_max_turns"')
    row = hl.run_task(task, ALIAS, {}, True, execute=_fake({}, capped, []), clock=_clock(0.0, 1.0))
    assert row["limit"] == f"headless_max_turns>{hl.MAX_TURNS}"


def _row(served="openai/Ornith-1.5-35B-Q4_K_M", alias=ALIAS, stream=1, **kw):
    return {"alias": alias, "served": served, "stream": stream, "tool_calls": 1, "tool_calls_valid": 1,
            "prompt_tokens": 900, "error_class": "", **kw}


def test_a_clean_run_passes_the_leak_check():
    got = headless.leak_check([_row(), _row(), _row(stream=0)], ALIAS, [ALIAS], 2)
    assert got["ok"] and got["streamed"] == 2 and got["background"] == 1 and got["served"] == ["openai/Ornith-1.5-35B-Q4_K_M"] and got["tool_calls_valid"] == 3


@pytest.mark.parametrize("rows,usage,calls,needle", [
    ([_row(), _row(served="anthropic/claude-opus-5-5", alias=ALIAS)], [ALIAS], 2, "anthropic/"),
    ([_row(), _row(alias="cloud-opus")], [ALIAS], 2, "other aliases"),
    ([_row()], [ALIAS], 3, "only 1 reached"),
    ([_row(), _row(stream=0)], [ALIAS], 2, "only 1 reached"),
    ([_row()], [ALIAS, "claude-haiku-4-5"], 1, "claude-haiku"),
    ([], [], 0, "nothing is proven"),
])
def test_every_way_a_call_escapes_fails_the_leak_check(rows, usage, calls, needle):
    got = headless.leak_check(rows, ALIAS, usage, calls)
    assert not got["ok"] and needle in "; ".join(got["problems"])


def _store(path: Path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE gateway_requests (id INTEGER PRIMARY KEY, at REAL, alias TEXT, served TEXT, "
                 "client TEXT, call_type TEXT, prompt_tokens INT, completion_tokens INT, tool_calls INT, "
                 "tool_calls_valid INT, finish_reason TEXT, error_class TEXT, stream INT)")
    conn.executemany("INSERT INTO gateway_requests (at, alias, served, client) VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_the_window_reads_only_claude_cli_rows_and_cannot_write(tmp_path):
    db = tmp_path / "store.db"
    _store(db, [(10.0, ALIAS, "s", "claude-cli/2.1.296"), (11.0, ALIAS, "s", "Python-urllib/3.12"),
                (50.0, ALIAS, "s", "claude-cli/2.1.296"), (12.0, ALIAS, "s", "claude-cli/2.1.296")])
    got = headless.requests_between(db, 9.0, 20.0)
    assert [r["at"] for r in got] == [10.0, 12.0]
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True).execute(
            "DELETE FROM gateway_requests")


def test_leaks_are_checked_per_task_and_over_the_whole_run(tmp_path):
    rows = [{"start": 10.0, "end": 20.0, "model_usage": [ALIAS], "api_calls": 1},
            {"start": 30.0, "end": 40.0, "model_usage": [ALIAS], "api_calls": 1}]
    windows = []

    def query(store, start, end):
        windows.append((start, end))
        return [_row()] if end < 30 else [_row(served="anthropic/claude-opus-5-5")]
    whole = hl.attach_leaks(rows, tmp_path / "x.db", ALIAS, settle_s=2.0, query=query)
    assert windows == [(10.0, 22.0), (30.0, 42.0), (10.0, 42.0)]
    assert rows[0]["leak"]["ok"] and not rows[1]["leak"]["ok"] and not whole["ok"]


def test_a_task_window_stops_where_the_next_task_starts(tmp_path):
    rows = [{"start": 10.0, "end": 20.0, "model_usage": [ALIAS], "api_calls": 1},
            {"start": 21.0, "end": 40.0, "model_usage": [ALIAS], "api_calls": 1}]
    windows = []
    hl.attach_leaks(rows, tmp_path / "x.db", ALIAS, settle_s=3.0,
                    query=lambda store, s, e: windows.append((s, e)) or [_row()])
    assert windows[0] == (10.0, 21.0)


def test_the_summary_rate_counts_invalid_calls_over_all_calls():
    got = hl.summary([{"passed": True, "turns": 3, "tool_calls": 4, "invalid_calls": 1, "wall_s": 2.0},
                      {"passed": False, "turns": None, "tool_calls": 0, "invalid_calls": 0, "wall_s": 1.0}])
    assert got == {"tasks": 2, "passed": 1, "turns": 3, "tool_calls": 4, "invalid_calls": 1,
                   "valid_rate": 0.75, "wall_s": 3.0}


def test_soh_headless_env_prints_the_profile_and_no_key(capsys, monkeypatch):
    from harness import cli
    monkeypatch.setenv("SOHOT_GATEWAY_KEY", SECRET)
    assert cli.main(["headless", "env", "--model", ALIAS, "--gateway", "http://gw:4000"]) == 0
    out = capsys.readouterr().out
    assert "export ANTHROPIC_BASE_URL=http://gw:4000" in out and SECRET not in out
