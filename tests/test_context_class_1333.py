"""#1333: carried context by class, KB hits referenced later, Reads never edited, from synthetic transcripts."""
import json
from datetime import datetime, timezone

import pytest

from harness import cli
from harness import context_class as cc
from harness import context_report as cr

T0 = datetime(2026, 10, 20, tzinfo=timezone.utc)
SEARCH = "mcp__mcm-engine__search"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def call(mid, tokens_in, uses=(), text="ok"):
    content = [{"type": "tool_use", "id": uid, "name": name, "input": inp} for uid, name, inp in uses]
    return {"type": "assistant", "timestamp": iso(T0), "message": {
        "id": mid, "role": "assistant", "content": content or [{"type": "text", "text": text}],
        "usage": {"input_tokens": tokens_in, "output_tokens": 1}}}


def result(uid, text):
    return {"type": "user", "timestamp": iso(T0), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": text}]}}


def compact():
    return {"type": "system", "subtype": "compact_boundary", "timestamp": iso(T0)}


def hits(*ids, pad=0):
    body = "\n\n".join(f"[{kind} #{n}] title {n}: " + "w" * pad for kind, n in ids)
    return json.dumps({"result": body})


def session(root, lines):
    p = root / "p" / "s1.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def rows(got):
    return {r["class"]: r for r in got["rows"]}


@pytest.mark.parametrize("cmd, want", [
    ("cd /w && uv run pytest tests/x.py -q 2>&1 | tail -5", "Bash pytest / make check"),
    ("make check > ../c.log 2>&1; echo $?", "Bash pytest / make check"),
    ("gh issue view 12 | head -40", "Bash gh issue/pr view, gh api"),
    ("gh api repos/o/r/pulls/3/comments", "Bash gh issue/pr view, gh api"),
    ("git -C /w diff --stat origin/main", "Bash diff/log/show"),
    ("tail -50 /w/run.log", "Bash reading log/txt/jsonl files"),
    ("grep -c ok out/results.jsonl", "Bash reading log/txt/jsonl files"),
    ("sed -n 1,80p harness/cli.py", "Bash cat/sed/head/tail/awk"),
    ("cat a.py | grep def", "Bash cat/sed/head/tail/awk"),
    ("rg -n carried harness/", "Bash rg/grep/find/ls"),
    ("cd /w && grep -n def a.py | head -20", "Bash rg/grep/find/ls"),
    ("ls -la /w", "Bash rg/grep/find/ls"),
    ("git status --short", "Bash git other"),
    ("python3 -c 'print(1)'", "Bash python"),
    ("echo hi", "Bash other"),
])
def test_bash_commands_fall_in_their_class(cmd, want):
    assert cc.bash_class(cmd) == want


@pytest.mark.parametrize("path, want", [
    ("/u/.claude/projects/p/s/tool-results/b1.txt", "tool output"),
    ("/private/tmp/x/tasks/b2.output", "tool output"),
    ("/w/tests/test_x.py", "tests"),
    ("/w/harness/cli.py", "python"),
    ("/w/README.md", "markdown"),
    ("/w/out.txt", ".txt"),
    ("/w/p.diff", ".diff"),
    ("/w/run.log", ".log"),
    ("/w/r.jsonl", ".jsonl"),
    ("/w/Makefile", "other"),
    ("/w/a.rs", "other"),
])
@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/context_class.py:_KINDS")
def test_read_paths_fall_in_their_kind(path, want):
    assert cc.file_kind(path) == want


def test_a_compaction_ends_carrying_for_a_class(tmp_path):
    session(tmp_path, [call("m1", 10, [("b1", "Bash", {"command": "sed -n 1,9p a.py"})]), result("b1", "x" * 400),
                       call("m2", 10), compact(), call("m3", 10), call("m4", 10)])
    got = cc.carried(tmp_path)
    assert rows(got)["Bash cat/sed/head/tail/awk"]["carried"] == 100
    assert got["compactions"] == 1


def test_a_hit_referenced_by_id_and_one_by_get_entry_both_count(tmp_path):
    shown = hits(("KNOWLEDGE/FINDING", 11), ("RULE", 12), ("NEGATIVE", 13), ("ERROR", 14), ("RULE", 15),
                 ("RULE", 16), pad=1000)
    session(tmp_path, [
        call("m1", 10, [("s1", SEARCH, {"query": "carried"})]), result("s1", shown),
        call("m2", 10, text="per RULE #16 the fix is known"),
        call("m3", 10, [("g1", "mcp__mcm-engine__get_entry", {"entity_type": "negative", "entry_id": 13})]),
        result("g1", "body"),
        call("m4", 10, [("g2", "mcp__mcm-engine__get_entry", {"entity_type": "rule", "entry_id": 11})]),
        result("g2", "body")])
    got = cc.carried(tmp_path, referenced=True)
    kb = got["kb"]
    assert (kb["searches"], kb["hits"], kb["referenced"], kb["unreferenced_searches"]) == (1, 6, 2, 0)
    assert kb["at_6_or_later"] == 1
    assert got["searches"][0]["positions"] == [3, 6]


def test_a_hit_named_before_its_search_is_not_referenced(tmp_path):
    session(tmp_path, [call("m0", 10, text="see #11"),
                       call("m1", 10, [("s1", SEARCH, {"query": "x"})]),
                       result("s1", hits(("RULE", 11), pad=4000)), call("m2", 10)])
    kb = cc.carried(tmp_path, referenced=True)["kb"]
    assert (kb["hits"], kb["referenced"], kb["unreferenced_searches"]) == (1, 0, 1)


def test_a_read_followed_by_an_edit_of_the_same_path_is_not_exploratory(tmp_path):
    session(tmp_path, [
        call("m1", 10, [("r1", "Read", {"file_path": "/w/harness/a.py"}),
                        ("r2", "Read", {"file_path": "/w/harness/b.py"})]),
        result("r1", "a" * 8000), result("r2", "b" * 4000),
        call("m2", 10, [("e1", "Edit", {"file_path": "/w/harness/a.py", "old_string": "a", "new_string": "c"})]),
        result("e1", "ok"),
        call("m3", 10, [("r3", "Read", {"file_path": "/w/harness/a.py"})]), result("r3", "c" * 400),
        call("m4", 10)])
    got = rows(cc.carried(tmp_path))
    assert got["Read python, edited later"]["results"] == 1
    assert got["Read python, edited later"]["entered"] == 2000
    assert got["Read python, never edited"]["results"] == 2
    assert got["Read python, never edited"]["entered"] == 1000 + 100
    assert got["Read python, never edited"]["results_1k"] == 1


def test_claudes_own_blocks_are_carried_beside_tool_output(tmp_path):
    session(tmp_path, [
        call("m1", 10, [("b1", "Bash", {"command": "echo " + "q" * 395})]), result("b1", ""),
        call("m2", 10, [("w1", "Write", {"file_path": "/w/tests/test_a.py", "content": "t" * 800})]),
        result("w1", ""),
        call("m3", 10, [("b2", "Bash", {"command": "gh pr create --body " + "p" * 380})]), result("b2", ""),
        call("m4", 10), call("m5", 10)])
    got = rows(cc.carried(tmp_path))
    assert got["own Bash command"]["carried"] == 100 * 4
    assert got["own Write tests"]["carried"] == 200 * 3
    assert got["own issue/PR/commit body"]["carried"] == 100 * 2
    assert got["own Bash command"]["kind"] == "own"
    assert got["Bash other"]["kind"] == "output"


def test_class_totals_match_the_per_tool_walk(tmp_path):
    session(tmp_path, [call("m1", 100, [("b1", "Bash", {"command": "ls"}), ("r1", "Read", {"file_path": "/a.md"}),
                                        ("s1", SEARCH, {"query": "q"})]),
                       result("b1", "x" * 400), result("r1", "y" * 800), result("s1", hits(("RULE", 1))),
                       call("m2", 300), compact(), call("m3", 500)])
    by_class, by_tool = cc.carried(tmp_path), cr.carried(tmp_path)
    assert by_class["input"] == by_tool["input"] == 900
    assert by_class["carried"] == by_tool["carried"]
    assert rows(by_class)["KB search"]["carried"] == next(t["carried"] for t in by_tool["tools"]
                                                         if t["tool"] == "mcm-engine search")


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                       site="env:SOH_CLAUDE_PROJECTS")
def test_soh_context_carried_by_class_reports_classes_and_references(tmp_path, monkeypatch, capsys):
    session(tmp_path, [
        {"type": "user", "timestamp": iso(T0), "message": {"role": "user", "content": "SECRET"}},
        call("m1", 100, [("s1", SEARCH, {"query": "q"})]), result("s1", hits(("RULE", 7), ("RULE", 8), pad=2000)),
        call("m2", 300, text="RULE #8 applies"), call("m3", 600)])
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    assert cli.main(["context", "--since", "2026-10-01", "--carried", "--by", "class", "--referenced",
                     "--json"]) == 0
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err
    data = json.loads(out.out)
    search = next(r for r in data["rows"] if r["class"] == "KB search")
    entered = len(hits(("RULE", 7), ("RULE", 8), pad=2000)) // 4
    assert (data["input"], search["entered"], search["carried"]) == (1000, entered, 2 * entered)
    assert (data["kb"]["hits"], data["kb"]["referenced"]) == (2, 1)
    assert data["searches"][0]["positions"] == [2]
    assert cli.main(["context", "--since", "2026-10-01", "--carried", "--by", "class"]) == 0
    assert "KB search" in capsys.readouterr().out


def test_by_class_needs_carried(tmp_path, monkeypatch):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    assert cli.main(["context", "--by", "class", "--json"]) == 2
