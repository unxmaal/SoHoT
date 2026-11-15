"""A PostToolUse hook hands oversized Bash and Read results to the local lanes, keeps the raw, never loses output. #2032."""
import functools
import io
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from harness import delegate, delegations, digest, paths
from harness import tool_route as tr
from harness.commands import tool_route as cmd

KEEP = "E       AssertionError: the planted must-keep line"
FAILED = "FAILED tests/test_planted.py::test_the_planted_failure - assert False"


def _answer(text):
    def complete(lane, prompt, **kw):
        complete.calls += 1
        return {"text": text, "spec": "s", "model": "m", "prompt_tokens": 100, "completion_tokens": 10}
    complete.calls = 0
    return complete


@pytest.fixture
def wt(tmp_path):
    root = tmp_path / "wt"
    (root / ".git").mkdir(parents=True)
    return root


def _bash(wt, stdout, command="make test", stderr=""):
    return {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "toolu_01abc", "cwd": str(wt),
            "tool_input": {"command": command, "description": "Run the tests"},
            "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False,
                              "noOutputExpected": False}}


def _big():
    rows = [f"tests/test_mod_{i}.py::test_case_{i} PASSED" for i in range(600)]
    rows[300:300] = ["_" * 10 + " test_the_planted_failure " + "_" * 10, KEEP]
    return "\n".join(rows + [FAILED, "=== 1 failed, 600 passed in 12.00s ==="]) + "\n"


def _rows(call_id):
    with delegations.ledger() as conn:
        return [tuple(r) for r in conn.execute("SELECT lane FROM delegations WHERE call_id = ?", (call_id,))]


def test_a_large_bash_output_is_digested_counted_and_kept_whole(wt):
    stdout, stderr = _big(), "warning: planted on stderr"
    run = functools.partial(digest.run, complete=_answer("1 test failed: test_the_planted_failure"))
    got = tr.hook(_bash(wt, stdout, stderr=stderr), digest_run=run)
    out = got["hookSpecificOutput"]["updatedToolOutput"]
    assert set(out) == {"stdout", "stderr", "interrupted", "isImage", "noOutputExpected"} and out["stderr"] == ""
    shown = out["stdout"]
    assert shown.startswith("[soh tool-route:") and len(shown) < len(stdout) / 4
    assert KEEP in shown and "test_the_planted_failure" in shown
    raw = Path(shown.split("the whole output is ", 1)[1].split(";", 1)[0])
    assert raw.parent == wt / "tmp" / "tool-route"
    assert raw.read_text(encoding="utf-8") == stdout + "\n" + stderr
    call_id = shown.split("call_id ", 1)[1].split(";", 1)[0]
    assert call_id.startswith("local-") and _rows(call_id) == [("extract",)]


def test_a_small_output_passes_through_unchanged(wt):
    complete = _answer("never asked")
    event = _bash(wt, "ok\n" * 100)
    assert tr.hook(event, digest_run=functools.partial(digest.run, complete=complete)) is None
    assert complete.calls == 0 and not (wt / "tmp").exists()
    out = io.StringIO()
    sys.stdout, keep = out, sys.stdout
    try:
        assert cmd.cmd_tool_route(types.SimpleNamespace(hook=True, chars=None), stdin=io.StringIO(json.dumps(event))) == 0
    finally:
        sys.stdout = keep
    assert out.getvalue() == ""


@pytest.mark.parametrize("how", ["refused", "raises"])
def test_a_local_lane_failure_passes_the_original_through(wt, how):
    def busy(lane, prompt, **kw):
        raise delegate.Refused("a batch run holds the machine")
    run = (functools.partial(digest.run, complete=busy) if how == "refused"
           else lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lane down")))
    assert tr.hook(_bash(wt, _big()), digest_run=run) is None
    assert list((wt / "tmp" / "tool-route").glob("*.log")) == []


def test_the_hook_command_prints_nothing_when_the_lane_fails(wt, monkeypatch, capsys):
    monkeypatch.setattr(digest, "run", lambda *a, **kw: {"unmodelled": "down", "text": "x", "call_id": ""})
    event = json.dumps(_bash(wt, _big()))
    assert cmd.cmd_tool_route(types.SimpleNamespace(hook=True, chars=None), stdin=io.StringIO(event)) == 0
    assert capsys.readouterr().out == ""
    assert cmd.cmd_tool_route(types.SimpleNamespace(hook=True, chars=None), stdin=io.StringIO("not json")) == 0
    assert capsys.readouterr().out == ""


def test_the_escape_hatches_leave_the_result_whole(wt):
    assert tr.wanted(_bash(wt, _big()))
    assert not tr.wanted(_bash(wt, _big(), command="SOH_RAW=1 make test"))
    assert not tr.wanted(_bash(wt, _big()), env={"SOH_ROUTE": "off"})
    assert not tr.wanted(_bash(wt, _big()), chars=10 ** 6)
    assert not tr.wanted({**_bash(wt, _big()), "tool_name": "Grep"})


def _read(wt, tmp_path, offset=None):
    target = wt / "big.py"
    content = "".join(f"def f_{i}():\n    return {i}\n" for i in range(800))
    target.write_text(content, encoding="utf-8")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Where is f_400 defined?"}]}}) + "\n", encoding="utf-8")
    lines = content.count("\n")
    ti = {"file_path": str(target), **({"offset": offset} if offset else {})}
    return {"hook_event_name": "PostToolUse", "tool_name": "Read", "cwd": str(wt), "transcript_path": str(transcript),
            "tool_input": ti, "tool_response": {"type": "text", "file": {
                "filePath": str(target), "content": content, "numLines": lines, "startLine": 1, "totalLines": lines}}}


def test_a_whole_file_read_goes_through_spans_with_the_sessions_need(wt, tmp_path):
    seen = {}

    def ask_file(raw, question, **kw):
        seen.update(raw=raw, question=question)
        return {"mode": "spans", "call_id": "local-c1", "lane": "code", "text": "   801\tdef f_400():"}
    event = _read(wt, tmp_path)
    out = tr.hook(event, ask_file=ask_file)["hookSpecificOutput"]["updatedToolOutput"]
    assert seen == {"raw": [event["tool_input"]["file_path"]], "question": "Where is f_400 defined?"}
    assert out["type"] == "text" and "def f_400():" in out["file"]["content"] and "local-c1" in out["file"]["content"]
    assert out["file"]["filePath"] == event["tool_input"]["file_path"]
    assert tr.hook(_read(wt, tmp_path, offset=10), ask_file=ask_file) is None


def test_a_read_the_spans_lane_returns_whole_passes_through(wt, tmp_path):
    assert tr.hook(_read(wt, tmp_path), ask_file=lambda *a, **kw: {"mode": "whole", "call_id": "", "text": "x"}) is None
    assert tr.hook(_read(wt, tmp_path), ask_file=lambda *a, **kw: 1 / 0) is None


def test_the_hook_script_passes_small_and_broken_events_at_once(wt):
    script = paths.REPO / "scripts" / "tool-route-hook.py"
    for given in (json.dumps(_bash(wt, "ok\n")), "not json"):
        got = subprocess.run([sys.executable, str(script)], input=given, capture_output=True, text=True, timeout=30)
        assert got.returncode == 0 and got.stdout == ""


def test_install_merges_the_block_once_and_keeps_the_rest(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "x", "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": []}]}}),
                        encoding="utf-8")
    block = tr.settings(cmd.command(tr.CHARS, tr.TIMEOUT_S - 10), tr.TIMEOUT_S)
    assert tr.install(settings, block) == "added" and tr.install(settings, block) == "present"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "x" and [e["matcher"] for e in data["hooks"]["PostToolUse"]] == ["Edit", "Bash|Read"]
    assert data["hooks"]["PostToolUse"][1]["hooks"][0]["command"].endswith(f"tool-route-hook.py {tr.CHARS} 110")


def test_a_second_install_with_new_settings_replaces_the_old_hook_not_beside_it(tmp_path):
    settings = tmp_path / "settings.json"
    other = {"type": "command", "command": "mcm-engine hook"}
    old = tr.settings(cmd.command(4000, 50), 60)
    old["hooks"]["PostToolUse"][0]["hooks"].append(other)
    settings.write_text(json.dumps(old), encoding="utf-8")
    assert tr.install(settings, tr.settings(cmd.command(16000, 110), 120)) == "replaced"
    hooks = [h for e in json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"] for h in e["hooks"]]
    assert [h["command"] for h in hooks if tr.SCRIPT in h["command"]] == [cmd.command(16000, 110)]
    assert other in hooks


def test_an_install_while_another_holds_the_settings_file_is_refused_and_writes_nothing(tmp_path, monkeypatch):
    import contextlib

    from harness import exclusive
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    taken = []
    monkeypatch.setattr(exclusive, "alone", lambda name, wait_s: taken.append(name) or contextlib.nullcontext(False))
    with pytest.raises(RuntimeError, match="another soh tool-route --install"):
        tr.install(settings, tr.settings(cmd.command(tr.CHARS, 110), tr.TIMEOUT_S))
    assert settings.read_text(encoding="utf-8") == "{}" and taken and taken[0].endswith(".lock")


def test_install_from_a_home_that_is_not_the_live_one_is_refused(tmp_path, monkeypatch, capsys):
    from harness import cli
    settings = tmp_path / "settings.json"
    assert cli.main(["tool-route", "--install", str(settings)]) == 1
    assert "not the live home" in capsys.readouterr().out and not settings.exists()
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    assert cli.main(["tool-route", "--install", str(settings)]) == 0
    assert tr.SCRIPT in settings.read_text(encoding="utf-8")
