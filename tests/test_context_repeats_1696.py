"""#1696: repeated KB mistakes and known-bad command rates, main vs subagent, on planted transcripts and KB rows."""
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from harness import cli
from harness import context_mistakes as cm
from harness import context_repeats as cx

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
CANARY = "CANARY-1696-text"
WAITER = 'until ! pgrep -f "make check" >/dev/null; do sleep 10; done'
GUARDED = "while pgrep -f '[b]in/lh discover' >/dev/null; do sleep 5; done"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def at(day, hour=0, minute=0):
    return T0 + timedelta(days=day, hours=hour, minutes=minute)


def use(uid, when, name, inp):
    return {"type": "assistant", "timestamp": iso(when), "message": {
        "id": f"m-{uid}", "role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": name, "input": inp}]}}


def bash(uid, when, cmd):
    return use(uid, when, "Bash", {"command": cmd})


def kb_call(uid, when, tool, inp, text):
    return [use(uid, when, f"mcp__mcm-engine__{tool}", inp),
            {"type": "user", "timestamp": iso(when + timedelta(seconds=3)), "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": uid, "content": [{"type": "text", "text": text}]}]}}]


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def kb_text(rows):
    out = []
    for kind, n, when, text in rows:
        out.append(f"#{n} [{kind}] {text}\n  hash=abc | updated={when.isoformat(sep=' ')}\n  what_failed: {CANARY}")
    return "\n\n".join(out) + "\n\n--- page: n entries (cap 100). next: scroll_entries('rule', after_id=9)\n"


def build(tmp_path):
    """Main: 10 Bash calls before the lesson (one unguarded waiter), 10 after (a guarded waiter, git add -A).
    Its subagent: 9 calls after the lesson, three of them the same unguarded waiter, plus a forked copy of a main call."""
    main = [bash(f"b{i}", at(1, 1, i), f"ls {CANARY}") for i in range(9)] + [bash("w0", at(1, 2), WAITER)]
    main += [bash(f"a{i}", at(8, 1, i), f"ls {CANARY}") for i in range(8)]
    main += [bash("g0", at(8, 2), GUARDED), bash("add0", at(8, 3), f"git add -A && git commit -m {CANARY}")]
    main += kb_call("e0", at(9, 1), "report_error", {"error_text": f"swept {CANARY}"}, "Logged error #3")
    sub = [bash("add0", at(8, 3), "git add -A && git commit -m x")]
    sub += [bash(f"s{i}", at(8, 4, i), f"ls {CANARY}") for i in range(6)]
    sub += [bash(f"sw{i}", at(8, 5, i), WAITER) for i in range(3)]
    sub += kb_call("q0", at(8, 6), "search", {"query": "pgrep"}, f"[RULE #906] waiters {CANARY}\n[RULE #7] other")
    sub += kb_call("q1", at(8, 6, 5), "search", {"query": "deploy"}, "No results")
    sub += kb_call("n0", at(8, 7), "add_negative", {"what_failed": f"pgrep {CANARY}"}, "Stored negative")
    write(tmp_path / "proj" / "s.jsonl", main)
    write(tmp_path / "proj" / "s" / "subagents" / "workflows" / "w1" / "agent-x.jsonl", sub)
    kb = tmp_path / "kb.txt"
    kb.write_text(kb_text([
        ("negative", 1, at(-10), f"git-hygiene git add -A swept files {CANARY}"),
        ("rule", 906, at(5), f"a waiter must never use pgrep -f {CANARY}"),
        ("rule", 7, at(4), f"unrelated {CANARY}"),
        ("negative", 2, at(8, 7) + timedelta(seconds=2), f"shell pgrep -f waiter never exits {CANARY}"),
        ("error", 3, at(9, 1) + timedelta(seconds=2), f"git add -A swept the untracked files {CANARY}"),
        ("error", 4, at(9, 2), f"nothing known {CANARY}"),
    ]), encoding="utf-8")
    return kb


def rate(got, name):
    return next(r for r in got["rates"] if r["pattern"] == name)


def test_counts_on_planted_transcripts_and_kb_rows(tmp_path):
    kb = build(tmp_path)
    got = cx.measure(tmp_path, cm.load_rows(str(kb), cx.KB_KINDS))
    assert got["bash"] == {"main": 20, "sub": 9}
    w = rate(got, "pgrep-f-waiter")
    assert w["lesson_at"] == at(5).timestamp()
    assert w["kinds"]["main"] == {"calls": 1, "bash": 20, "per_1k": 50.0, "streams": 1, "streams_2plus": 0,
                                  "self_copies": 0}
    assert w["kinds"]["sub"] == {"calls": 3, "bash": 9, "per_1k": 333.33, "streams": 1, "streams_2plus": 1,
                                 "self_copies": 2}
    assert {k: (v["calls"], v["bash"]) for k, v in w["split"].items()} == {
        "before main": (1, 10), "after main": (0, 10), "after sub": (3, 9)}
    assert [(x["week"], x["kind"], x["calls"], x["bash"]) for x in w["weeks"]] == [
        ("2026-W40", "main", 1, 10), ("2026-W41", "main", 0, 10), ("2026-W41", "sub", 3, 9)]
    assert rate(got, "git-add-all")["kinds"]["main"]["calls"] == 1
    assert rate(got, "git-add-all")["kinds"]["sub"]["calls"] == 0


def test_each_repeat_names_its_earlier_entry_and_what_its_stream_was_shown(tmp_path):
    kb = build(tmp_path)
    got = cx.measure(tmp_path, cm.load_rows(str(kb), cx.KB_KINDS))
    reps = {(r["kind"], r["id"], r["class"]): r for r in got["repeats"]}
    assert set(reps) == {("negative", 2, "pgrep-f-waiter"), ("error", 3, "git-add-all")}
    neg = reps[("negative", 2, "pgrep-f-waiter")]
    assert (neg["earlier"], neg["first"], neg["earlier_n"], neg["recorded"]) == ("RULE #906", "RULE #906", 1, "sub")
    assert (neg["queries"], neg["topical"], neg["returned"], neg["on_record"]) == (2, 1, ["RULE #906"], [])
    err = reps[("error", 3, "git-add-all")]
    assert (err["earlier"], err["recorded"], err["queries"], err["returned"]) == ("NEGATIVE #1", "main", 0, [])
    s = got["summary"]
    assert s["repeat_rows"] == {"negative": 1, "error": 1} and s["rows"] == {"negative": 2, "error": 2}
    assert (s["no_query"], s["topical_query"], s["returned_before"]) == (1, 1, 1)
    assert s["recorded"] == {"negative sub": 1, "error main": 1}


def test_a_lesson_returned_only_after_the_recording_call_is_not_counted(tmp_path):
    kb = build(tmp_path)
    got = cx.measure(tmp_path, cm.load_rows(str(kb), cx.KB_KINDS), lookback=60)
    neg = next(r for r in got["repeats"] if r["id"] == 2)
    assert (neg["queries"], neg["returned"]) == (0, [])


def test_the_pattern_table_is_the_single_source(tmp_path, monkeypatch, capsys):
    kb = build(tmp_path)
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    planted = cx.Pattern("planted-ls", r"\bnothing known\b", r"^ls\b", "RULE #7")
    monkeypatch.setattr(cx, "PATTERNS", cx.PATTERNS + (planted,))
    assert cli.main(["context", "--mistakes", "--repeats", "--kb", str(kb), "--json"]) == 0
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    row = next(r for r in got["rates"] if r["pattern"] == "planted-ls")
    assert (row["kinds"]["main"]["calls"], row["kinds"]["sub"]["calls"]) == (17, 6)
    assert row["split"]["before main"]["calls"] == 9
    assert next(c for c in got["classes"] if c["class"] == "planted-ls")["error"] == 1


def test_no_transcript_or_kb_text_reaches_the_output(tmp_path, monkeypatch, capsys):
    kb = build(tmp_path)
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    assert cli.main(["context", "--mistakes", "--repeats", "--kb", str(kb)]) == 0
    assert cli.main(["context", "--mistakes", "--repeats", "--kb", str(kb), "--json"]) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "pgrep-f-waiter" in text and "NEGATIVE #2" in text and "2026-W41" in text
    assert "CANARY" not in text and "make check" not in text


def test_repeats_needs_mistakes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    assert cli.main(["context", "--repeats", "--kb", "x", "--json"]) == 2
    assert "--mistakes" in capsys.readouterr().out


def test_rows_keep_their_text_and_rule_rows_are_read_on_request():
    text = kb_text([("rule", 5, at(0), "a rule"), ("negative", 6, at(1), "a negative")])
    assert [(r["kind"], r["id"]) for r in cm.parse_rows(text)] == [("negative", 6)]
    rows = cm.parse_rows(text, cx.KB_KINDS)
    assert [(r["kind"], r["id"]) for r in rows] == [("rule", 5), ("negative", 6)]
    assert rows[0]["text"].startswith("a rule") and CANARY in rows[0]["text"] and "updated=" not in rows[0]["text"]
    assert "--- page" not in rows[1]["text"]


EXAMPLES = {
    "pgrep-f-waiter": ([WAITER, "while pgrep -qf soh-loop; do sleep 1; done", "until ! pgrep -fl x; do :; done"],
                       [GUARDED, "pgrep -f x", "while kill -0 $PID; do sleep 1; done",
                        "for i in 1 2; do sleep 1; done; while pgrep -f '[x]y'; do :; done"]),
    "git-add-all": (["git add -A && git commit -m x", "git -C repo add --all", "git add -A"],
                    ["git add -A harness/x.py", "git add harness/x.py", "git add -u"]),
    "pipe-tail-then-commit": (["make test 2>&1 | tail -3 && git commit -m x"],
                              ["make test && git commit -m x", "make test | tail -3; echo done"]),
    "launchctl-disable": (["launchctl disable gui/1/x"], ["launchctl enable gui/1/x", "launchctl print gui/1/x"]),
    "pytest-n-auto": (["uv run pytest tests/ -q -n auto", "pytest -nauto"], ["pytest -n 6", "make check"]),
    "checkout-ref-restore": (["git checkout HEAD -- harness/x.py", "git checkout origin/main -- a b"],
                             ["git checkout -b x origin/main", "git checkout -- a"]),
    "checkout-index-restore": (["git checkout -- harness/x.py"], ["git checkout HEAD -- x", "git checkout main"]),
}


@pytest.mark.parametrize("pattern", [p for p in cx.PATTERNS if p.command], ids=lambda p: p.name)
def test_every_command_pattern_matches_its_examples_and_not_their_safe_forms(pattern):
    hits, misses = EXAMPLES[pattern.name]
    rx = re.compile(pattern.command)
    assert all(rx.search(c) for c in hits), [c for c in hits if not rx.search(c)]
    assert not any(rx.search(c) for c in misses), [c for c in misses if rx.search(c)]
