"""#1336: exploratory reads as spans checked against the file, the whole file on any doubt, recall and redo from synthetic transcripts."""
import json
from datetime import datetime, timezone

import pytest

from evals import spans_recall as sr
from harness import spans

T0 = datetime(2026, 10, 20, tzinfo=timezone.utc)
LINES = [f"def helper_{i}(x):  # line {i}" if i % 10 == 0 else f"    value_{i} = x + {i}" for i in range(1, 301)]
TEXT = "\n".join(LINES) + "\n"


def quote(a, b, lines=LINES):
    return f"@@ {a}-{b}\n" + "\n".join(lines[a - 1:b]) + "\n"


def model(*replies, tokens=10):
    calls = []

    def complete(lane, prompt, **kw):
        calls.append(prompt)
        r = replies[min(len(calls), len(replies)) - 1]
        if isinstance(r, Exception):
            raise r
        return {"text": r, "model": "fake", "completion_tokens": tokens}
    complete.calls = calls
    return complete


def test_verified_quotes_come_back_as_numbered_spans_only():
    got = spans.answer(TEXT, "what does helper_20 do?", complete=model(quote(20, 22) + quote(100, 100)))
    assert got.mode == spans.SPANS and got.spans == [(20, 22), (100, 100)]
    assert got.body.splitlines()[0] == f"    20\t{LINES[19]}"
    assert LINES[50] not in got.body
    assert spans.verbatim(TEXT, got.body)
    assert got.header("f.py").startswith("spans: f.py lines 20-22, 100-100 of 300")


def anchors(a, b, lines=LINES):
    return f"@@ {a}-{b}\n{lines[a - 1]}\n{lines[b - 1]}\n"


def test_first_and_last_line_anchor_a_span_and_are_checked():
    got = spans.answer(TEXT, "q", complete=model(anchors(20, 29) + f"@@50\n{LINES[49]}\n"))
    assert got.spans == [(20, 29), (50, 50)] and LINES[24] in got.body and spans.verbatim(TEXT, got.body)
    assert spans.answer(TEXT, "q", complete=model(anchors(20, 29).replace(LINES[28], LINES[27]))).code == "quote"
    assert spans.answer(TEXT, "q", complete=model(f"@@ 20-29\n{LINES[19]}\n")).spans == [(20, 29)]
    inline = f"@@ 20-29 | {LINES[19].strip()}\n@@ 77-78 |{LINES[76]}\n"
    assert spans.answer(TEXT, "q", complete=model(inline)).spans == [(20, 29), (77, 78)]
    assert spans.answer(TEXT, "q", complete=model(f"@@ 20-29 | {LINES[20]}\n")).code == "quote"
    assert spans.answer(TEXT, "q", complete=model("@@ 20-29 |  \n")).code == "quote"
    assert spans.answer(TEXT, "q", complete=model("@@ 20-29 | (x):\n")).code == "quote"
    diff = ["+def added_function(a, b):" if i == 40 else f"+    total_{i} = a + {i}" for i in range(1, 301)]
    got = spans.answer("\n".join(diff), "q", complete=model("@@ 40-44 | def added_function(a, b):\n"))
    assert got.spans == [(40, 44)] and "+def added_function" in got.body
    numbered = f"@@ 20-29\n20|{LINES[19]}\n29|{LINES[28]}\n"
    assert spans.answer(TEXT, "q", complete=model(numbered)).spans == [(20, 29)]


@pytest.mark.parametrize("reply, code", [
    (quote(20, 22).replace("value_21", "value_2l"), "quote"),
    (quote(20, 22).replace("    value_21", "value_21"), "quote"),
    ("@@ 20-22\n" + "\n".join(LINES[19:21]) + "\n", "quote"),
    ("insufficient", "insufficient"),
    ("none", "none"),
    ("helper_20 adds twenty.", "format"),
    (quote(299, 300) + "@@ 300-301\nx\n", "range"),
    (quote(1, 200), "share"),
])
def test_any_doubt_returns_the_whole_file(reply, code):
    got = spans.answer(TEXT, "q", complete=model(reply))
    assert (got.mode, got.code) == (spans.WHOLE, code)
    assert got.body.count("\n") == len(LINES) - 1 and spans.verbatim(TEXT, got.body)


def test_a_failed_or_cut_off_call_returns_the_whole_file():
    assert spans.answer(TEXT, "q", complete=model(RuntimeError("gateway down"))).code == "model"
    assert spans.answer(TEXT, "q", complete=model(quote(20, 22), tokens=spans.REPLY_TOKENS)).code == "budget"


def test_a_short_file_comes_back_whole_without_a_call():
    fake = model(quote(1, 1))
    got = spans.answer("a = 1\n", "q", complete=fake)
    assert (got.mode, got.code, fake.calls) == (spans.WHOLE, "short", [])


def test_tolerates_fences_and_number_prefixes_but_still_checks_them():
    fenced = "Here they are:\n```\n" + quote(30, 31) + "```\n"
    assert spans.answer(TEXT, "q", complete=model(fenced)).spans == [(30, 31)]
    numbered = "@@ 30-31\n" + "\n".join(f"{i}|{LINES[i - 1]}" for i in (30, 31))
    assert spans.answer(TEXT, "q", complete=model(numbered)).spans == [(30, 31)]
    wrong = "@@ 30-31\n" + "\n".join(f"{i}|{LINES[i - 1]}" for i in (31, 32))
    assert spans.answer(TEXT, "q", complete=model(wrong)).code == "quote"


def test_a_long_file_is_asked_in_parts_with_absolute_line_numbers():
    size = (len(TEXT) + 8 * len(LINES)) // 2 + 40
    assert [last for _, last in spans.parts(LINES, size)][-1] == 300 and len(spans.parts(LINES, size)) == 2
    fake = model("none", quote(250, 251))
    got = spans.answer(TEXT, "q", complete=fake, size=size)
    assert got.spans == [(250, 251)] and len(fake.calls) == 2
    assert "250|" + LINES[249] in fake.calls[1] and "250|" not in fake.calls[0]
    assert spans.answer(TEXT, "q", complete=model(quote(250, 251)), size=size).code == "range"


def test_model_habits_are_read_but_still_checked():
    prose = "The question asks about it.\n" + quote(20, 22) + "@@ 20-22\n"
    assert spans.answer(TEXT, "q", complete=model(prose)).spans == [(20, 22)]
    assert spans.answer(TEXT, "q", complete=model("Nothing here is relevant.\n\nnone")).code == "none"
    blank = ["x" * 50, "", "y" * 50] * 40
    text = "\n".join(blank)
    assert spans.answer(text, "q", complete=model(f"@@ 1-3\n{'x' * 50}\n|\n{'y' * 50}\n")).spans == [(1, 3)]
    assert spans.answer(text, "q", complete=model(f"@@ 1-3\n{'x' * 50}\n|z\n{'y' * 50}\n")).code == "quote"


def test_verbatim_catches_a_changed_line():
    body = spans.render(LINES, [(5, 6)])
    assert spans.verbatim(TEXT, body)
    assert not spans.verbatim(TEXT, body.replace("value_5", "value_6"))
    assert not spans.verbatim(TEXT, body.replace("     5\t", "     7\t"))


def test_local_reads_through_the_1335_roots_and_returns_local_completes_shape(tmp_path):
    from harness import ask
    (tmp_path / "a.py").write_text(TEXT, encoding="utf-8")
    roots = [ask.Root(tmp_path)]
    fake = model(quote(20, 22))
    got = spans.ask_file(str(tmp_path / "a.py"), "q", roots=roots, complete=fake)
    assert got["mode"] == spans.SPANS and got["text"].startswith("spans: ") and got["calls"] == 1
    assert got["files"] == [{"path": str((tmp_path / "a.py").resolve()), "bytes": len(TEXT)}]
    outside = tmp_path.parent / "outside-1336.py"
    outside.write_text(TEXT, encoding="utf-8")
    (tmp_path / "link.py").symlink_to(outside)
    for raw in (str(outside), str(tmp_path / "link.py")):
        with pytest.raises(ask.Refused):
            spans.ask_file(raw, "q", roots=roots, complete=fake)
    with pytest.raises(ask.Refused, match="one file"):
        spans.ask_file([str(tmp_path / "a.py")] * 2, "q", roots=roots, complete=fake)
    with pytest.raises(ask.Refused, match="question"):
        spans.ask_file(str(tmp_path / "a.py"), " ", roots=roots, complete=fake)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def use(mid, *uses, text=""):
    content = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": uid, "name": name, "input": inp} for uid, name, inp in uses]
    return {"type": "assistant", "timestamp": iso(T0), "message": {"id": mid, "role": "assistant", "content": content}}


def read_result(uid, path, text):
    n = text.count("\n")
    return {"type": "user", "timestamp": iso(T0), "toolUseResult": {"type": "text", "file": {
        "filePath": path, "content": text, "startLine": 1, "numLines": n, "totalLines": n}},
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": uid, "content": "..."}]}}


def result(uid, text):
    return {"type": "user", "timestamp": iso(T0), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": text}]}}


def test_gold_is_what_later_inputs_used_from_the_file_and_nothing_knew_before():
    recs = [
        use("m0", ("b0", "Bash", {"command": "grep -n helper_10 a.py"})),
        use("m1", ("r1", "Read", {"file_path": "/w/a.py"}), text="Find how helper_40 builds its value."),
        read_result("r1", "/w/a.py", TEXT),
        use("m2", ("e2", "Edit", {"file_path": "/w/b.py", "old_string": "x", "new_string": "helper_40(value_41) + helper_10"})),
        use("m3", ("r3", "Read", {"file_path": "/w/c.py"})),
        read_result("r3", "/w/c.py", TEXT),
        use("m4", ("e4", "Edit", {"file_path": "/w/c.py", "old_string": "helper_70 + value_71", "new_string": "y"})),
    ]
    got = sr.stream_cases(recs, None, "t")
    assert len(got) == 1, "c.py is edited later, so only a.py is an exploratory read"
    case = got[0]
    assert case.idents == ["helper_40", "helper_70", "value_41", "value_71"] and "They said: Find how helper_40 builds its value." in case.question
    hit = spans.answer(TEXT, case.question, complete=model(quote(40, 41) + quote(70, 71)))
    miss = spans.answer(TEXT, case.question, complete=model(quote(40, 40)))
    assert sr.score(case, hit)["found"] == 4 and sr.score(case, miss)["found"] == 1


def test_run_writes_numbers_only_and_scores_the_bars(tmp_path):
    case = sr.Case("c1", "python", "q", TEXT, ["helper_40", "value_41"], [])
    good = sr.run([case], lambda t, q: spans.answer(t, q, complete=model(quote(40, 41))), tmp_path / "o")
    assert good["passes"] and good["recall"] == 1.0 and good["verbatim"] == 1
    row = json.loads((tmp_path / "o" / "results.jsonl").read_text(encoding="utf-8"))
    assert "helper_40" not in json.dumps(row) and row["found"] == 2
    bad = sr.run([case], lambda t, q: spans.answer(t, q, complete=model(quote(40, 40))), tmp_path / "o")
    assert not bad["passes"] and bad["recall"] == 0.5
    whole = sr.run([case], lambda t, q: spans.answer(t, q, complete=model("insufficient")), tmp_path / "o")
    assert not whole["passes"] and whole["whole_by"] == {"insufficient": 1}


@pytest.mark.parametrize("cmd, path", [
    ("cd /d && uv run soh spans /w/a.py -q 'what is x'", "/w/a.py"),
    ("soh spans -q 'what is x' --lane code /w/a.py 2>&1 | head -50", "/w/a.py"),
    ("soh ask /w/a.py -q x", ""),
    ("cat /w/a.py", ""),
])
def test_spanned_path(cmd, path):
    assert spans.spanned_path(cmd) == path


def test_a_full_read_soon_after_spans_is_a_redo():
    spans_call = ("s1", "Bash", {"command": "soh spans /w/a.py -q x"})
    full = ("r2", "Read", {"file_path": "/w/a.py"})
    part = ("r3", "Read", {"file_path": "/w/a.py", "offset": 10, "limit": 5})
    filler = [use(f"f{k}", (f"g{k}", "Bash", {"command": "ls"})) for k in range(spans.REDO_WINDOW)]
    redone = [use("m1", spans_call), result("s1", "spans: /w/a.py lines 1-2 of 9"), use("m2", part), use("m3", full)]
    late = [use("m1", spans_call), result("s1", "spans: /w/a.py lines 1-2 of 9"), *filler, use("m3", full)]
    whole = [use("m1", spans_call), result("s1", "whole: /w/a.py, 9 lines (none)"), use("m3", full)]
    assert spans.redos([redone]) == {"calls": 1, "redos": 1, "rate": 1.0}
    assert spans.redos([late]) == {"calls": 1, "redos": 0, "rate": 0.0}
    assert spans.redos([whole])["calls"] == 0
    tool = ("s1", "mcp__soh__local_complete", {"paths": ["/w/a.py"], "question": "x", "mode": "spans"})
    via_mcp = [use("m1", tool), result("s1", json.dumps({"text": "spans: /w/a.py", "mode": "spans"})), use("m3", full)]
    assert spans.redos([via_mcp]) == {"calls": 1, "redos": 1, "rate": 1.0}
    whole_mcp = [use("m1", tool), result("s1", json.dumps({"text": "whole: /w/a.py", "mode": "whole"})), use("m3", full)]
    assert spans.redos([whole_mcp])["calls"] == 0


@pytest.fixture
def mcp_server():
    return pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")


def test_the_tool_returns_spans_of_one_path_through_the_same_boundary(mcp_server, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from mcp.server.mcpserver.exceptions import ToolError

    from harness import ask, delegate
    fake = model(quote(20, 22))
    monkeypatch.setattr(delegate, "complete", fake)
    monkeypatch.setenv(ask.ROOTS_ENV, str(tmp_path))
    (tmp_path / "a.py").write_text(TEXT, encoding="utf-8")
    got = mcp_server.local_complete(paths=[str(tmp_path / "a.py")], question="q", mode="spans")
    assert got.mode == spans.SPANS and [tuple(x) for x in got.spans] == [(20, 22)]
    assert got.lane == "code" and got.text.startswith("spans: ") and got.call_id
    remote = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(
        client=SimpleNamespace(host="203.0.113.31"), scope={"server": ("203.0.113.1", 8000)})))
    with pytest.raises(ToolError, match="only a caller on it"):
        mcp_server.local_complete(paths=[str(tmp_path / "a.py")], question="q", mode="spans", ctx=remote)
    with pytest.raises(ToolError, match="outside the roots"):
        mcp_server.local_complete(paths=["/"], question="q", mode="spans")
    with pytest.raises(ToolError, match="pass it in `paths`"):
        mcp_server.local_complete(question="q", mode="spans")
    with pytest.raises(ToolError, match="mode is"):
        mcp_server.local_complete(prompt="p", mode="digest")
    assert len(fake.calls) == 1


@pytest.fixture
def live_home(tmp_path, monkeypatch):
    from harness import memory_store as ms, paths
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setenv(paths.ENV_VAR, str(live))
    ms.connect().close()
    monkeypatch.setattr(paths, "DEFAULT_HOME", live)
    monkeypatch.delenv(paths.ENV_VAR)
    return live / "discovery.db"


def test_the_redo_and_eval_run_from_a_scratch_home(live_home, tmp_path):
    from harness import cli, paths
    before = live_home.read_bytes()
    assert cli.main(["spans", "--redo", "--root", str(tmp_path / "none")]) == 0
    assert not paths.is_live(paths.home() / "discovery.db")
    cli.main(["spans", "--eval", str(tmp_path / "ev"), "--root", str(tmp_path / "none"), "--n", "1"])
    assert paths.home() == (tmp_path / "ev" / "home").resolve() and live_home.read_bytes() == before


def test_naming_the_live_home_is_refused_unless_asked_for(live_home, tmp_path, monkeypatch, capsys):
    from harness import cli, paths
    monkeypatch.setenv(paths.ENV_VAR, str(live_home.parent))
    assert cli.main(["spans", "--redo", "--root", str(tmp_path)]) == 2
    assert "--live-home" in capsys.readouterr().out
    assert cli.main(["spans", "--redo", "--root", str(tmp_path), "--live-home"]) == 0
