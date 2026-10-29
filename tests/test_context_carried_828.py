"""#828: tool output carried in context, as a share of every API call's input, from transcript fixtures."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from harness import cli
from harness import context_report as cr

T0 = datetime(2026, 10, 20, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def call(mid, tokens_in, uses=(), at=T0, **extra):
    content = [{"type": "tool_use", "id": uid, "name": name, "input": {}} for uid, name in uses]
    return {"type": "assistant", "timestamp": iso(at), **extra, "message": {
        "id": mid, "role": "assistant", "content": content or [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": tokens_in, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                  "output_tokens": 1}}}


def result(uid, chars, at=T0, **extra):
    return {"type": "user", "timestamp": iso(at), **extra, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": "x" * chars}]}}


def hook(event, chars, at=T0):
    return {"type": "attachment", "timestamp": iso(at), "attachment": {
        "type": "hook_additional_context", "hookEvent": event, "content": ["y" * chars]}}


def compact(at=T0):
    return {"type": "system", "subtype": "compact_boundary", "timestamp": iso(at)}


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def session(root, lines, name="s1", subs=None):
    write(root / "p" / f"{name}.jsonl", lines)
    for sub, rows in (subs or {}).items():
        write(root / "p" / name / "subagents" / f"{sub}.jsonl", rows)


def tools(got):
    return {t["tool"]: t for t in got["tools"]}


def test_a_result_is_carried_into_every_later_call(tmp_path):
    session(tmp_path, [call("m1", 100, [("u1", "Bash")]), result("u1", 400),
                       call("m2", 300), call("m3", 500)])
    got = cr.carried(tmp_path)
    assert (got["input"], got["api_calls"]) == (900, 3)
    bash = tools(got)["Bash"]
    assert (bash["results"], bash["entered"], bash["carried"]) == (1, 100, 200)
    assert bash["share"] == pytest.approx(200 / 900, abs=1e-4)


def test_a_compaction_ends_what_is_carried(tmp_path):
    session(tmp_path, [call("m1", 100, [("u1", "Bash")]), result("u1", 400),
                       call("m2", 300), compact(), call("m3", 500)])
    got = cr.carried(tmp_path)
    assert tools(got)["Bash"]["carried"] == 100
    assert got["compactions"] == 1


def test_a_message_split_over_records_is_one_call(tmp_path):
    session(tmp_path, [call("m1", 100, [("u1", "Read")]), result("u1", 40),
                       call("m2", 300), call("m2", 300), call("m2", 300)])
    got = cr.carried(tmp_path)
    assert (got["input"], got["api_calls"], tools(got)["Read"]["carried"]) == (400, 2, 10)


def test_calls_outside_the_window_are_not_counted_but_earlier_results_are_carried_into_it(tmp_path):
    early, late = T0 - timedelta(days=3), T0 + timedelta(hours=1)
    session(tmp_path, [call("m1", 100, [("u1", "Bash")], at=early), result("u1", 400, at=early),
                       call("m2", 300, at=early), call("m3", 500, at=late), call("m4", 700, at=late)])
    got = cr.carried(tmp_path, since=T0.timestamp())
    assert (got["input"], got["api_calls"]) == (1200, 2)
    assert tools(got)["Bash"]["carried"] == 200
    assert tools(got)["Bash"]["entered"] == 0


def test_a_subagent_carries_only_its_own_results(tmp_path):
    session(tmp_path, [call("m1", 100, [("a1", "Agent")]), result("a1", 80), call("m2", 200)],
            subs={"agent-1": [{"type": "user", "timestamp": iso(T0), "message": {"role": "user", "content": "go"}},
                              call("s1", 50, [("r1", "Read")]), result("r1", 4000),
                              call("s2", 1050), call("s3", 1100)]})
    got = cr.carried(tmp_path)
    assert got["input"] == 100 + 200 + 50 + 1050 + 1100
    assert tools(got)["Read"]["carried"] == 2000
    assert tools(got)["Agent"]["carried"] == 20
    assert got["streams"] == 2
    assert cr.carried(tmp_path, main_only=True)["streams"] == 1


def test_hook_context_is_counted_beside_tool_results(tmp_path):
    session(tmp_path, [call("m1", 100), hook("PreToolUse", 800), call("m2", 300)])
    assert tools(cr.carried(tmp_path))["hook PreToolUse"]["carried"] == 200


def test_a_headless_session_is_left_out(tmp_path):
    session(tmp_path, [call("m1", 100, [("u1", "Bash")], entrypoint="sdk-cli"), result("u1", 400),
                       call("m2", 300, entrypoint="sdk-cli")])
    assert cr.carried(tmp_path)["input"] == 0


def test_the_biggest_carrier_comes_first_not_the_biggest_result(tmp_path):
    session(tmp_path, [call("m1", 10, [("s", "mcp__mcm-engine__search")]), result("s", 800)]
            + [call(f"n{i}", 10) for i in range(10)]
            + [call("m2", 10, [("r", "Read")]), result("r", 2000), call("m3", 10)])
    got = cr.carried(tmp_path)
    assert [t["tool"] for t in got["tools"]] == ["mcm-engine search", "Read"]
    assert tools(got)["Read"]["entered"] > tools(got)["mcm-engine search"]["entered"]


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                       site="env:SOH_CLAUDE_PROJECTS")
def test_soh_context_carried_reports_the_share_of_input(tmp_path, monkeypatch, capsys):
    session(tmp_path, [{"type": "user", "timestamp": iso(T0), "message": {"role": "user", "content": "SECRET"}},
                       call("m1", 100, [("u1", "Bash")]), result("u1", 400), call("m2", 300)])
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    monkeypatch.setattr(cr.shutil, "which", lambda _: None)
    assert cli.main(["context", "--since", "2026-10-01", "--carried", "--json"]) == 0
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err
    data = json.loads(out.out)
    assert (data["input"], data["carried"]) == (400, 100)
    assert data["rows"] == [{"tool": "Bash", "results": 1, "entered": 100, "carried": 100, "share": 0.25}]


def test_carried_refuses_what_it_cannot_measure(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    assert cli.main(["context", "--carried", "--source", "otel", "--json"]) == 2
    assert cli.main(["context", "--carried", "--by", "day", "--json"]) == 2
