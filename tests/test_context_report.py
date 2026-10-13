"""#828: tool-result tokens from Claude Code transcripts, against fixtures with known totals."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from harness import cli
from harness import context_report as cr

T0 = datetime(2026, 10, 7, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def use(uid, name, at=T0):
    return {"timestamp": iso(at), "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": uid, "name": name, "input": {}}]}}


def result(uid, content, at=T0):
    return {"timestamp": iso(at), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": content}]}}


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def by_tool(rows):
    return {r["tool"]: r for r in cr.summarize(rows)}


def test_exact_totals(tmp_path):
    p = write(tmp_path / "s.jsonl", [
        use("u1", "Bash"), result("u1", "x" * 400),
        use("u2", "Bash"), result("u2", "x" * 8000),
        use("u3", "Bash"), result("u3", "x" * 15),
        use("u4", "mcp__mcm-engine__search"), result("u4", "x" * 10004),
    ])
    s = cr.summarize(cr.scan([p]))
    assert [r["tool"] for r in s] == ["mcm-engine search", "Bash"]
    bash, search = s[1], s[0]
    assert (bash["calls"], bash["tokens"], bash["p50"], bash["max"]) == (3, 2103, 100, 2000)
    assert bash["share_over_2k"] == 0.0
    assert (search["calls"], search["tokens"], search["share_over_2k"]) == (1, 2501, 1.0)


def test_streamed_assistant_and_repeated_result_counted_once(tmp_path):
    p = write(tmp_path / "s.jsonl", [use("u1", "Bash"), use("u1", "Bash"),
                                     result("u1", "x" * 400), result("u1", "x" * 400)])
    t = by_tool(cr.scan([p]))
    assert (t["Bash"]["calls"], t["Bash"]["tokens"]) == (1, 100)


def test_list_content_counts_text_blocks_and_images_as_zero(tmp_path):
    p = write(tmp_path / "s.jsonl", [use("u1", "Read"), result("u1", [
        {"type": "text", "text": "x" * 40},
        {"type": "image", "source": {"type": "base64", "data": "A" * 9000}},
        {"type": "text", "text": "x" * 8}])])
    assert by_tool(cr.scan([p]))["Read"]["tokens"] == 12


def test_unknown_tool_use_id_is_its_own_row(tmp_path):
    p = write(tmp_path / "s.jsonl", [use("u1", "Bash"), result("u1", "x" * 40),
                                     result("nope", "x" * 400)])
    t = by_tool(cr.scan([p]))
    assert (t["?"]["calls"], t["?"]["tokens"], t["Bash"]["tokens"]) == (1, 100, 10)


def test_result_before_its_use_and_across_files_still_named(tmp_path):
    a = write(tmp_path / "a.jsonl", [result("u1", "x" * 40)])
    b = write(tmp_path / "b.jsonl", [use("u1", "Grep")])
    assert by_tool(cr.scan([a, b]))["Grep"]["calls"] == 1


def test_window_is_by_entry_timestamp_and_until_exclusive(tmp_path):
    h = timedelta(hours=1)
    p = write(tmp_path / "s.jsonl", [
        use("u1", "Bash", T0 - h), result("u1", "x" * 400, T0 - h),
        use("u2", "Bash", T0), result("u2", "x" * 800, T0),
        use("u3", "Bash", T0 + h), result("u3", "x" * 1600, T0 + h)])
    rows = cr.scan([p], since=T0.timestamp(), until=(T0 + h).timestamp())
    assert by_tool(rows)["Bash"]["tokens"] == 200


def test_subagents_included_unless_main_only(tmp_path):
    write(tmp_path / "proj" / "sess.jsonl", [use("u1", "Bash"), result("u1", "x" * 40)])
    write(tmp_path / "proj" / "sess" / "subagents" / "agent-a.jsonl",
          [use("u2", "Bash"), result("u2", "x" * 80)])
    assert by_tool(cr.scan(cr.transcripts(tmp_path)))["Bash"]["tokens"] == 30
    assert by_tool(cr.scan(cr.transcripts(tmp_path, main_only=True)))["Bash"]["tokens"] == 10


def test_by_day(tmp_path):
    d2 = T0 + timedelta(days=1)
    p = write(tmp_path / "s.jsonl", [use("u1", "Bash"), result("u1", "x" * 40),
                                     use("u2", "Bash", d2), result("u2", "x" * 80, d2)])
    s = cr.summarize(cr.scan([p]), by="day")
    assert [(r["day"], r["tokens"]) for r in s] == [("2026-10-07", 10), ("2026-10-08", 20)]


def test_parse_when():
    now = T0.timestamp()
    assert cr.parse_when("7d", now) == now - 7 * 86400
    assert cr.parse_when("2026-10-07", now) == now
    assert cr.parse_when("2026-10-07T01:00Z", now) == now + 3600


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                       site="env:SOH_CLAUDE_PROJECTS")
def test_cli_json_has_no_prompt_text_and_omits_rtk_when_absent(tmp_path, monkeypatch, capsys):
    write(tmp_path / "p" / "s.jsonl", [
        {"timestamp": iso(T0), "message": {"role": "user", "content": "SECRET-PROMPT"}},
        use("u1", "Bash"), result("u1", "SECRET-OUTPUT" + "x" * 27)])
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    monkeypatch.setattr(cr.shutil, "which", lambda _: None)
    assert cli.main(["context", "--since", "2026-10-01", "--json"]) == 0
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err
    data = json.loads(out.out)
    assert data["rows"] == [{"tool": "Bash", "calls": 1, "tokens": 10, "p50": 10, "p95": 10,
                             "max": 10, "share_over_2k": 0.0}]
    assert "rtk" not in data


def test_rtk_gain_reads_summary_when_present(monkeypatch):
    class P:
        returncode, stdout = 0, '{"summary": {"total_saved": 9}}'
    monkeypatch.setattr(cr.shutil, "which", lambda _: "/bin/rtk")
    assert cr.rtk_gain(runner=lambda *a, **k: P())["summary"]["total_saved"] == 9
