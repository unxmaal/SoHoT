"""local_complete reads paths itself: confined reads, chunked digests, the redo measure and the planted eval. #1335."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import ask_plants
from harness import ask, delegate, purpose
from tests.test_mcp_delegate import Fake, fake  # noqa: F401

LC = "mcp__soh__local_complete"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    return r


@pytest.fixture
def outside(tmp_path):
    o = tmp_path / "outside"
    o.mkdir()
    secret = o / "secret.txt"
    secret.write_text("the private thing\n", encoding="utf-8")
    return secret


def _roots(root):
    return [ask.Root(root)]


# ---- confinement --------------------------------------------------------------

def test_a_file_inside_a_root_is_read_with_its_real_path_and_byte_count(root):
    f = root / "make-check.log"
    f.write_text("ok\nFAILED tests/test_a.py::test_b\n", encoding="utf-8")
    [got] = ask.read([str(f)], _roots(root))
    assert got.path == os.path.realpath(f) and got.size == f.stat().st_size
    assert "test_b" in got.text


def test_a_file_outside_every_root_is_refused(root, outside):
    with pytest.raises(ask.Refused, match="outside the roots"):
        ask.read([str(outside)], _roots(root))


def test_dot_dot_out_of_a_root_is_refused(root, outside):
    with pytest.raises(ask.Refused, match="outside the roots"):
        ask.read([str(root / ".." / "outside" / "secret.txt")], _roots(root))


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlink_inside_a_root_to_a_file_outside_is_refused(root, outside):
    (root / "link.log").symlink_to(outside)
    with pytest.raises(ask.Refused, match="symlink out of the roots"):
        ask.read([str(root / "link.log")], _roots(root))


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlinked_directory_out_of_a_root_is_refused(root, outside):
    (root / "dir").symlink_to(outside.parent, target_is_directory=True)
    with pytest.raises(ask.Refused, match="symlink out of the roots"):
        ask.read([str(root / "dir" / "secret.txt")], _roots(root))


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlink_that_stays_inside_the_root_is_read(root):
    (root / "real.log").write_text("x\n", encoding="utf-8")
    (root / "alias.log").symlink_to(root / "real.log")
    [got] = ask.read([str(root / "alias.log")], _roots(root))
    assert got.path == os.path.realpath(root / "real.log")


@pytest.mark.skipif(sys.platform == "win32", reason="hard links behave differently on Windows")
def test_a_hard_link_is_refused_since_realpath_cannot_see_where_it_points(root, outside):
    os.link(outside, root / "hard.log")
    with pytest.raises(ask.Refused, match="hard links"):
        ask.read([str(root / "hard.log")], _roots(root))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no fifos here")
def test_a_fifo_is_refused_without_blocking_on_open(root):
    os.mkfifo(root / "pipe.log")
    with pytest.raises(ask.Refused, match="not a regular file"):
        ask.read([str(root / "pipe.log")], _roots(root))


def test_a_directory_is_refused(root):
    (root / "sub").mkdir()
    with pytest.raises(ask.Refused, match="not a regular file"):
        ask.read([str(root / "sub")], _roots(root))


def test_bytes_over_the_cap_are_refused_before_anything_is_read(root, monkeypatch):
    a, b = root / "a.log", root / "b.log"
    a.write_text("x" * 600, encoding="utf-8")
    b.write_text("y" * 600, encoding="utf-8")
    monkeypatch.setattr(ask, "_open", lambda *x: pytest.fail("opened a file over the cap"))
    with pytest.raises(ask.Refused, match="1200 bytes in 2 file"):
        ask.read([str(a), str(b)], _roots(root), max_bytes=1000)


def test_a_binary_file_is_refused(root):
    (root / "core").write_bytes(b"\x7fELF\x00\x00\x01")
    with pytest.raises(ask.Refused, match="binary"):
        ask.read([str(root / "core")], _roots(root))


@pytest.mark.parametrize("raw, match", [("", "empty path"), ("a\0b", "NUL"), ("rel.log", "absolute path")])
def test_malformed_paths_are_refused(root, raw, match):
    with pytest.raises(ask.Refused, match=match):
        ask.read([raw], _roots(root))


def test_a_relative_path_resolves_against_the_callers_directory(root):
    (root / "rel.log").write_text("x\n", encoding="utf-8")
    [got] = ask.read(["rel.log"], _roots(root), cwd=root)
    assert got.path == os.path.realpath(root / "rel.log")


def test_too_many_paths_are_refused(root):
    with pytest.raises(ask.Refused, match="path cap"):
        ask.read([str(root / f"{i}.log") for i in range(ask.MAX_PATHS + 1)], _roots(root))


def test_claude_projects_are_read_only_under_tool_results(tmp_path, monkeypatch):
    monkeypatch.setenv(ask.CLAUDE_ENV, str(tmp_path / "claude"))
    session = tmp_path / "claude" / "projects" / "-proj" / "abc"
    (session / "tool-results").mkdir(parents=True)
    (session / "tool-results" / "out.txt").write_text("x\n", encoding="utf-8")
    (session / "chat.jsonl").write_text("{}\n", encoding="utf-8")
    roots = ask.claude_roots()
    assert ask.read([str(session / "tool-results" / "out.txt")], roots)
    with pytest.raises(ask.Refused, match="outside the roots"):
        ask.read([str(session / "chat.jsonl")], roots)


def test_configured_roots_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(ask.ROOTS_ENV, os.pathsep.join([str(tmp_path / "a"), "", str(tmp_path / "b")]))
    assert [r.path for r in ask.configured()] == [tmp_path / "a", tmp_path / "b"]


def test_the_cli_callers_worktree_is_a_root(tmp_path):
    (tmp_path / "wt" / ".git").mkdir(parents=True)
    (tmp_path / "wt" / "deep").mkdir()
    roots = ask.default_roots(tmp_path / "wt" / "deep")
    assert Path(os.path.realpath(tmp_path / "wt")) in [r.path for r in roots]


# ---- chunks and digests -------------------------------------------------------

def _file(text, name="x.log"):
    return ask.File(f"/r/{name}", len(text), text)


def test_chunks_cut_on_line_boundaries_keep_every_line_in_order_and_name_the_lines():
    text = "".join(f"line {i:04d}\n" for i in range(500))
    parts = ask.chunks([_file(text)], size=1000)
    assert len(parts) > 1
    bodies = [p.split("\n", 1)[1] for p in parts]
    assert "".join(bodies) == text
    assert all(len(b) <= 1000 for b in bodies)
    assert parts[0].startswith("=== x.log, lines 1-") and parts[-1].split("\n", 1)[0].endswith("-500 ===")


def test_a_line_longer_than_a_chunk_is_split_rather_than_overflowing():
    parts = ask.chunks([_file("z" * 2500 + "\n")], size=1000)
    assert all(len(p.split("\n", 1)[1]) <= 1000 for p in parts) and len(parts) == 3


def test_a_short_file_is_one_call_and_its_answer_is_returned():
    seen = []
    text, parts, calls = ask.digest([_file("FAILED tests/t.py::test_q\n")], "what failed?",
                                    lambda p: seen.append(p) or "test_q")
    assert (text, parts, calls) == ("test_q", 1, 1) and "test_q" in seen[0] and "what failed?" in seen[0]


def test_long_files_map_then_merge_and_parts_that_answer_none_are_dropped():
    text = "".join(f"ok {i}\n" for i in range(400)) + "FAILED test_needle\n"
    prompts = []

    def call(p):
        prompts.append(p)
        if p.startswith(ask.MERGE):
            return "test_needle"
        return "test_needle" if "FAILED test_needle" in p else "NOT FOUND"
    got, parts, calls = ask.digest([_file(text)], "what failed?", call, size=500)
    assert got == "test_needle" and parts > 2
    assert calls == parts and not any(p.startswith(ask.MERGE) for p in prompts)


def test_two_parts_that_answer_are_merged_into_one():
    text = "FAILED test_one\n" + "".join(f"ok {i}\n" for i in range(200)) + "FAILED test_two\n"

    def call(p):
        if p.startswith(ask.MERGE):
            assert "test_one" in p and "test_two" in p
            return "test_one\ntest_two"
        return "\n".join(t for t in ("test_one", "test_two") if f"FAILED {t}" in p) or "none"
    got, parts, calls = ask.digest([_file(text)], "what failed?", call, size=400)
    assert got == "test_one\ntest_two" and calls == parts + 1


def test_every_part_answering_none_is_none_without_a_merge():
    got, parts, calls = ask.digest([_file("ok\n" * 400)], "q", lambda p: "None.", size=300)
    assert got == ask.NONE and calls == parts


@pytest.mark.parametrize("answer, none", [("none", True), ("NOT FOUND", True), ("`None`", True),
                                          ("None found.", True), ("", True),
                                          ("none of the 3 errors were fixed; KeyError: 'x'", False),
                                          ("test_none_handling", False)])
def test_what_counts_as_no_answer(answer, none):
    assert ask.is_none(answer) is none


def test_ask_returns_the_answer_paths_and_bytes_never_the_file(root, monkeypatch):
    f = root / "pytest.log"
    f.write_text("secret filler line\nFAILED tests/t.py::test_q\n", encoding="utf-8")
    calls = []

    def complete(lane, prompt, **kw):
        calls.append((lane, kw))
        return {"text": "test_q", "spec": "s", "model": "m", "ttft_s": 0.1,
                "prompt_tokens": 5, "completion_tokens": 2}
    got = ask.ask([str(f)], "what failed?", roots=_roots(root), complete=complete)
    assert got["text"] == "FAILED tests/t.py::test_q" and "secret filler" not in json.dumps(got)
    assert got["files"] == [{"path": os.path.realpath(f), "bytes": f.stat().st_size}]
    assert calls[0][0] == "extract" and calls[0][1]["system"] == ask.SYSTEM
    assert calls[0][1]["tag"] == purpose.INTERNAL


def test_the_code_lane_answers_with_thinking_off_unless_told(root):
    """One digest budget on every lane: the code lane answers without reasoning, so it spends it on the answer."""
    (root / "d.diff").write_text("+x\n", encoding="utf-8")
    seen = []

    def complete(lane, prompt, **kw):
        assert kw["max_tokens"] == ask.REPLY_TOKENS
        seen.append(kw["thinking"])
        return {"text": "x", "spec": "s", "model": "m"}
    ask.ask([str(root / "d.diff")], "q", lane="code", roots=_roots(root), complete=complete)
    ask.ask([str(root / "d.diff")], "q", lane="code", roots=_roots(root), complete=complete, thinking=True)
    ask.ask([str(root / "d.diff")], "q", roots=_roots(root), complete=complete)
    assert seen == [False, True, None]


def test_a_delegated_ask_is_work_and_one_delegations_row(root, monkeypatch):
    (root / "a.log").write_text("ok\n" * 300, encoding="utf-8")
    from harness import delegations
    noted, tags = [], []
    monkeypatch.setattr(delegations, "note", lambda got, cid, gateway=False: noted.append(cid) or {**got, "call_id": cid})

    def complete(lane, prompt, **kw):
        tags.append(kw["tag"])
        return {"text": "none", "spec": "s", "model": "m"}
    got = ask.ask([str(root / "a.log")], "q", roots=_roots(root), complete=complete, delegated=True, size=200)
    assert len(tags) > 1 and set(tags) == {purpose.WORK}
    assert noted == [got["call_id"]] and got["calls"] == len(tags)


def test_ask_goes_through_the_lanes_real_completion(fake, root):  # noqa: F811
    fake.reply = "test_q"
    (root / "a.log").write_text("FAILED test_q\n", encoding="utf-8")
    got = ask.ask([str(root / "a.log")], "what failed?", roots=_roots(root))
    assert got["text"] == "FAILED test_q" and set(fake.routed) == {"extract"}
    assert fake.seen[-1]["messages"][0]["content"] == ask.SYSTEM


def test_the_chunk_follows_a_small_served_context(monkeypatch):
    from harness import context
    monkeypatch.setattr(delegate, "route", lambda lane, chosen=None, via="": ("m", None))
    monkeypatch.setattr(context, "served_ctx", lambda spec: 4096)
    assert ask.chunk_chars("extract", 600) == (4096 - 600 - 1024) * delegate.CHARS_PER_TOKEN
    monkeypatch.setattr(context, "served_ctx", lambda spec: None)
    assert ask.chunk_chars("extract", 600) == ask.CHUNK_CHARS


# ---- who may pass paths -------------------------------------------------------

def _req(host, server=("203.0.113.20", 8899)):
    return SimpleNamespace(client=SimpleNamespace(host=host) if host else None, scope={"server": server})


@pytest.mark.parametrize("request_, local", [
    (None, True),
    (_req("127.0.0.1"), True),
    (_req("::1"), True),
    (_req("::ffff:127.0.0.1"), True),
    (_req("203.0.113.20"), True),
    (_req("203.0.113.31"), False),
    (_req(None), False),
    (_req("testclient"), False),
])
def test_only_a_caller_on_this_machine_may_pass_paths(request_, local):
    assert ask.local_client(request_) is local


# ---- the redo measure ---------------------------------------------------------

def _transcript(tmp_path, uses, stamp="2026-10-28T10:00:00Z"):
    path = tmp_path / "transcript.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for i, (name, given) in enumerate(uses):
            f.write(json.dumps({"timestamp": stamp, "message": {"content": [
                {"type": "tool_use", "id": f"t{i}", "name": name, "input": given}]}}) + "\n")
    return str(path)


def test_a_full_read_soon_after_a_digest_is_a_redo(tmp_path):
    path = _transcript(tmp_path, [(LC, {"paths": ["/a.txt"], "question": "q"}),
                                  ("Bash", {"command": "echo 1"}), ("Bash", {"command": "echo 2"}),
                                  ("Read", {"file_path": "/a.txt"})])
    got = ask.redos([path])
    assert (got["digests"], got["redos"], got["rate"]) == (1, 1, 1.0)
    assert got["examples"][0]["path"] == "/a.txt"


def test_a_partial_read_is_not_a_redo(tmp_path):
    path = _transcript(tmp_path, [(LC, {"paths": ["/a.txt"]}), ("Read", {"file_path": "/a.txt", "offset": 0}),
                                  ("Read", {"file_path": "/a.txt", "limit": 10})])
    assert ask.redos([path])["redos"] == 0


def test_a_read_past_the_window_is_not_a_redo(tmp_path):
    uses = [(LC, {"paths": ["/a.txt"]})] + [("Bash", {"command": f"echo {i}"}) for i in range(10)]
    path = _transcript(tmp_path, uses + [("Read", {"file_path": "/a.txt"})])
    assert ask.redos([path])["redos"] == 0
    path = _transcript(tmp_path, uses[:-1] + [("Read", {"file_path": "/a.txt"})])
    assert ask.redos([path])["redos"] == 1


def test_a_prompt_only_call_is_not_a_digest(tmp_path):
    path = _transcript(tmp_path, [(LC, {"prompt": "x"}), ("Read", {"file_path": "/a.txt"})])
    assert ask.redos([path]) == {"digests": 0, "redos": 0, "rate": None, "examples": []}


def test_digests_before_the_window_are_not_counted(tmp_path):
    path = _transcript(tmp_path, [(LC, {"paths": ["/a.txt"]}), ("Read", {"file_path": "/a.txt"})])
    since = datetime(2026, 10, 29, tzinfo=timezone.utc).timestamp()
    assert ask.redos([path], since=since)["digests"] == 0


# ---- the planted-failure eval -------------------------------------------------

def test_the_eval_logs_are_deterministic_and_each_plant_is_in_its_log_only():
    a, b = ask_plants.cases(24, seed=7), ask_plants.cases(24, seed=7)
    assert a == b and len({c["id"] for c in a}) == 24
    assert {(c["kind"], c["plant"]) for c in a} == {(k, p) for k in ask_plants.KINDS for p in ask_plants.PLANTS}
    for c in a:
        assert c["planted"] in c["text"] and c["planted"] not in c["clean"]
        assert "Traceback" not in c["clean"] and "FAILED" not in c["clean"] and "Error 1" not in c["clean"]


def test_some_eval_logs_are_long_enough_to_be_chunked():
    assert max(len(c["text"]) for c in ask_plants.cases(60)) > 2 * ask.CHUNK_CHARS


@pytest.mark.parametrize("answer, expect, hit", [
    ("FAILED tests/x.py::test_lane_slot - assert 1 == 2", "test_lane_slot", True),
    ("Found 17 errors.", "17", True),
    ("17 passed", "17", False),
    ("Found 170 errors.", "17", False),
    ("none", "test_lane_slot", False),
])
def test_a_plant_is_named_only_by_its_own_token(answer, expect, hit):
    assert ask_plants.named(answer, expect) is hit


def _oracle(path: str, question: str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    for c in ask_plants.cases(8, seed=3):
        if c["text"] == text:
            return f"{c['planted']} ({c['expect']} error)" if c["expect"].isdigit() else c["planted"]
    return "none"


def test_a_perfect_reader_passes_the_bars_and_a_silent_one_fails(tmp_path):
    good = ask_plants.run(tmp_path / "good", _oracle, n=8, seed=3)
    assert good["hits"] == 8 and good["nones"] == 8
    silent = ask_plants.run(tmp_path / "silent", lambda p, q: "none", n=8, seed=3)
    assert silent["hits"] == 0 and not silent["passes"]
    rows = [json.loads(x) for x in (tmp_path / "silent" / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 8 and "text" not in rows[0]


def test_a_reader_that_names_everything_fails_on_the_clean_twins(tmp_path):
    got = ask_plants.run(tmp_path, lambda p, q: "FAILED test_everything; 3 errors", n=8, seed=3)
    assert got["nones"] == 0 and not got["passes"]


def test_the_bars_need_the_wilson_bound_too():
    rows = [{"kind": "k", "plant": "p", "planted_answer": "x", "hit": True, "clean_answer": "none",
             "clean_none": True}] * 20
    assert ask_plants.score(rows)["hit_lower"] < ask_plants.HIT_LOWER_BAR
    assert not ask_plants.score(rows)["passes"]


# ---- the CLI and the MCP tool -------------------------------------------------

def test_soh_ask_reads_a_file_in_the_callers_worktree(tmp_path, monkeypatch, capsys):
    from harness import cli
    (tmp_path / ".git").mkdir()
    (tmp_path / "check.log").write_text("FAILED test_q\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(delegate, "complete", lambda lane, prompt, **kw: {"text": "test_q", "spec": "s", "model": "m"})
    assert cli.main(["ask", "check.log", "-q", "what failed?"]) == 0
    assert "test_q" in capsys.readouterr().out


def test_soh_ask_refuses_a_file_outside_and_says_why(tmp_path, monkeypatch, capsys, outside):
    from harness import cli
    (tmp_path / "wt" / ".git").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "wt")
    assert cli.main(["ask", str(outside), "-q", "q"]) == 1
    assert "outside the roots" in capsys.readouterr().out


@pytest.fixture
def mcp_server():
    return pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")


def test_the_tool_takes_paths_and_a_question_and_hides_its_context(mcp_server):
    tools = {t.name: t for t in mcp_server.SERVER._tool_manager.list_tools()}
    props = tools["local_complete"].parameters["properties"]
    assert {"paths", "question"} <= set(props) and "ctx" not in props


def test_the_tool_answers_from_paths_with_the_files_it_read(fake, mcp_server, root, monkeypatch):  # noqa: F811
    monkeypatch.setenv(ask.ROOTS_ENV, str(root))
    fake.reply = "test_q"
    (root / "a.log").write_text("FAILED test_q\n", encoding="utf-8")
    got = mcp_server.local_complete(paths=[str(root / "a.log")], question="what failed?")
    assert got.text == "FAILED test_q" and got.lane == "extract" and got.parts == 1
    assert got.files == [{"path": os.path.realpath(root / "a.log"), "bytes": 14}]
    assert fake.seen[-1]["max_tokens"] == ask.REPLY_TOKENS and got.call_id


def test_the_tool_refuses_a_path_outside_its_roots_as_an_mcp_error(fake, mcp_server, outside):  # noqa: F811
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="outside the roots"):
        mcp_server.local_complete(paths=[str(outside)], question="q")
    assert fake.seen == []


def test_the_tool_refuses_paths_from_another_machine(fake, mcp_server, root, monkeypatch):  # noqa: F811
    from mcp.server.mcpserver.exceptions import ToolError
    monkeypatch.setenv(ask.ROOTS_ENV, str(root))
    (root / "a.log").write_text("x\n", encoding="utf-8")
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=_req("203.0.113.31")))
    with pytest.raises(ToolError, match="only a caller on it"):
        mcp_server.local_complete(paths=[str(root / "a.log")], question="q", ctx=ctx)
    assert fake.seen == []


def test_a_question_without_paths_is_refused(mcp_server):
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="asks about `paths`"):
        mcp_server.local_complete(question="what failed?")


def test_a_prompt_alone_still_goes_to_the_code_lane_with_2048_tokens(fake, mcp_server):  # noqa: F811
    got = mcp_server.local_complete(prompt="write add")
    assert got.lane == "code" and fake.seen[-1]["max_tokens"] == 2048 and got.files is None


def test_each_limit_leaves_a_cut_when_it_binds(root, monkeypatch):
    from harness import cuts
    seen = []
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: seen.append(knob))
    (root / "a.log").write_text("ok\n" * 300, encoding="utf-8")
    with pytest.raises(ask.Refused):
        ask.read([str(root / "a.log")], _roots(root), max_bytes=10)
    with pytest.raises(ask.Refused):
        ask.read([str(root / "a.log")] * (ask.MAX_PATHS + 1), _roots(root))
    ask.ask([str(root / "a.log")], "q", roots=_roots(root), size=200, max_tokens=5,
            complete=lambda lane, p, **kw: {"text": "none", "spec": "s", "model": "m", "completion_tokens": 5})
    assert seen[:2] == ["harness/ask.py:MAX_BYTES", "harness/ask.py:MAX_PATHS"]
    assert {"harness/ask.py:CHUNK_CHARS", "harness/ask.py:REPLY_TOKENS"} <= set(seen)


def test_a_stray_none_line_beside_an_answer_is_dropped():
    assert ask.clean("85 errors in the lint step\nnone") == "85 errors in the lint step"
    assert ask.clean("none\n\nNOT FOUND") == ask.NONE


def test_answer_lines_the_files_never_hold_are_dropped_as_made_up():
    text = "tests/a.py::test_ok PASSED\nFAILED tests/b.py::test_real - assert 1 == 2\n"
    got = ask.ground("FAILED tests/b.py::test_real - assert 1 == 2\nFAILED tests/a.py::test_invented\n3",
                     text, "what failed?")
    assert got == "FAILED tests/b.py::test_real - assert 1 == 2"
    assert ask.ground("- `FAILED tests/b.py::test_real`", text, "q") == "- `FAILED tests/b.py::test_real`"
    assert ask.ground("3", text, "how many tests ran?") == "3"


def test_a_count_of_tests_that_did_not_fail_is_dropped_from_a_failure_answer():
    text = "===== 3000 passed, 3 xfailed, 12 warnings in 30.1s =====\n"
    assert ask.ground("3 xfailed\n12 warnings", text, "Did anything fail?") == ask.NONE
    assert ask.ground("3 xfailed", text, "how many xfailed?") == "3 xfailed"
    assert ask.ground("1 failed, 3000 passed", "1 failed, 3000 passed\n", "what failed?") == "1 failed, 3000 passed"


@pytest.mark.parametrize("line", [
    "Found 59 errors.", "finished: 300 cases, 46 errors, exit 1", "##[error]Process completed with exit code 2.",
    "make: *** [check] Error 1", "FAILED tests/b.py::test_real - assert 1 == 2", "tests/b.py::test_real FAILED [ 40%]",
    "RuntimeError: ledger_shard could not be resolved", "E   KeyError: 'slot'", "--- FAIL: TestQuota (0.02s)",
    "sqlite3.OperationalError: database is locked", "panic: shard closed", "error[E0425]: cannot find value `x`",
    "src/a.ts(3,5): error TS2339: Property 'x' does not exist", "Tests:       2 failed, 40 passed, 42 total",
    "Exception in thread \"main\" java.lang.IllegalStateException: closed", "FAILED (failures=2)",
    "2026-10-20T01:02:03.1234567Z Found 3 errors in 2 files"])
def test_a_failure_shaped_line_is_found(line):
    assert ask.failure_lines(f"ok\n{line}\nok\n")


@pytest.mark.parametrize("line", [
    "pressure level 1, swap 860 MiB, 0 errors so far", "finished: 300 cases, 0 errors, exit 0",
    "tests/test_error_x.py::test_raises_y PASSED [ 40%]", "tests/c.py::test_x XFAIL (known drift)",
    "  harness/a.py:12: DeprecationWarning: utcnow() is deprecated", "== 3000 passed, 3 xfailed, 2 warnings in 3.1s ==",
    "✖ 2 problems (0 errors, 2 warnings)", "test result: ok. 41 passed; 0 failed; 1 ignored",
    "retry route: HTTP 503 busy, attempt 1 of 3, waiting 2s", "--- PASS: TestErrorPath (0.01s)",
    "All checks passed!", "Success: no issues found in 212 source files", "OK (skipped=3, expected failures=1)",
    "tests/t.py::test_exit_code[exit 1] PASSED [ 40%]"])
def test_a_line_that_did_not_fail_is_not_found(line):
    assert ask.failure_lines(f"{line}\n") == []


def test_the_scan_adds_failure_lines_the_model_skipped_and_only_once():
    text = "ok\nFound 59 errors.\nFound 59 errors.\nFAILED tests/b.py::test_q - boom\n"
    assert ask.with_failures(ask.NONE, text) == ("Found 59 errors.\nFAILED tests/b.py::test_q - boom", 2)
    assert ask.with_failures("FAILED tests/b.py::test_q - boom", text) == (
        "FAILED tests/b.py::test_q - boom\nFound 59 errors.", 1)
    assert ask.with_failures(ask.NONE, "ok\nall good\n") == (ask.NONE, 0)
    stamped = "2026-10-20T01:02:03.1Z Found 3 errors."
    assert ask.with_failures(stamped, stamped + "\n") == (stamped, 0)


def test_a_quoted_fragment_does_not_hide_the_whole_failure_line():
    assert ask.with_failures("FAILED", "x FAILED\nFound 3 errors.\n") == ("x FAILED\nFound 3 errors.", 1)
    assert ask.with_failures("RuntimeError", "RuntimeError: slot_lane gone\n") == ("RuntimeError: slot_lane gone", 0)


def test_the_scan_keeps_its_first_lines_and_leaves_a_cut(monkeypatch):
    from harness import cuts
    seen = []
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: seen.append((knob, kw["dropped"])))
    text = "".join(f"FAILED tests/t.py::test_{i}\n" for i in range(ask.FAILURE_LINES + 5))
    got, added = ask.with_failures(ask.NONE, text)
    assert added == ask.FAILURE_LINES and got.splitlines()[0] == "FAILED tests/t.py::test_0"
    assert seen == [("harness/ask.py:FAILURE_LINES", 5)]


def test_a_long_line_is_clipped_around_its_failure_and_leaves_a_cut(monkeypatch):
    from harness import cuts
    seen = []
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: seen.append(knob))
    got = ask.failure_lines("x" * 2000 + " Found 7 errors. " + "y" * 2000 + "\nFound 2 errors.\n")
    assert len(got[0]) == ask.LINE_CHARS and "Found 7 errors." in got[0] and got[1] == "Found 2 errors."
    assert seen == ["harness/ask.py:LINE_CHARS"]


def test_ask_adds_the_scan_only_to_a_question_about_failures(root):
    (root / "a.log").write_text("ok\nFound 4 errors.\n", encoding="utf-8")
    reply = lambda lane, p, **kw: {"text": "none", "spec": "s", "model": "m"}  # noqa: E731
    got = ask.ask([str(root / "a.log")], "Did anything fail?", roots=_roots(root), complete=reply)
    assert got["text"] == "Found 4 errors." and got["scanned"] == 1
    got = ask.ask([str(root / "a.log")], "which python ran?", roots=_roots(root), complete=reply)
    assert got["text"] == ask.NONE and got["scanned"] == 0


@pytest.mark.parametrize("family", ["pytest", "fresh", "third"])
def test_each_eval_set_is_the_same_for_a_seed_and_its_clean_twins_hold_no_plant(family):
    from evals import ask_plants
    a, q = ask_plants.generated(family, 15, None)
    b, _ = ask_plants.generated(family, 15, None)
    c, _ = ask_plants.generated(family, 15, 7)
    assert a == b and a != c and q
    for r in a:
        assert ask_plants.named(r["text"], r["expect"], r.get("word") or "error")
        assert r["planted"] not in r["clean"]


def test_the_fresh_set_uses_other_tools_than_the_pytest_set():
    from evals import ask_plants, ask_plants_fresh, ask_plants_third
    sets = (ask_plants, ask_plants_fresh, ask_plants_third)
    assert len({k for s in sets for k in s.KINDS}) == sum(len(s.KINDS) for s in sets)
    assert len({s.QUESTION for s in sets}) == 3


def test_passing_status_lines_are_dropped_only_from_an_answer_about_failures():
    text = "tests/a.py::test_ok PASSED\ntests/c.py::test_x XFAIL (known)\n"
    assert ask.ground("tests/a.py::test_ok PASSED\ntests/c.py::test_x XFAIL", text, "Did anything fail?") == ask.NONE
    assert ask.ground("tests/c.py::test_x XFAIL", text, "which tests were xfailed?") == "tests/c.py::test_x XFAIL"


def test_a_made_up_note_never_reaches_the_answer():
    text = "ok\n" * 300 + "FAILED test_real\n"
    got, parts, calls = ask.digest([_file(text)], "what failed?",
                                   lambda p: "FAILED test_real" if "FAILED test_real" in p else "FAILED test_ghost",
                                   size=300)
    assert got == "FAILED test_real" and calls == parts


def test_a_passing_line_quoted_without_its_status_word_is_still_dropped():
    text = "tests/a.py::test_ok PASSED [ 10%]\nFAILED tests/b.py::test_bad - assert 1 == 2\n"
    assert ask.ground("tests/a.py::test_ok", text, "what failed?") == ask.NONE
    assert ask.ground("tests/b.py::test_bad", text, "what failed?") == "tests/b.py::test_bad"


# ---- evals and the redo measure never write the live store (#1346) ------------

@pytest.fixture
def live_home(tmp_path, monkeypatch):
    """A fixture home standing in for the live one: a migrated store with the limit_cuts table."""
    from harness import memory_store as ms, paths
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setenv(paths.ENV_VAR, str(live))
    ms.connect().close()
    monkeypatch.setattr(paths, "DEFAULT_HOME", live)
    monkeypatch.delenv(paths.ENV_VAR)
    return live / "discovery.db"


def _writes_to(monkeypatch, store: Path) -> list:
    import sqlite3
    seen, real = [], sqlite3.connect

    def spy(db, *args, **kw):
        raw = str(db)
        plain = raw.removeprefix("file:").split("?")[0]
        if Path(plain).resolve() == store.resolve() and "mode=ro" not in raw:
            seen.append(raw)
        return real(db, *args, **kw)
    monkeypatch.setattr(sqlite3, "connect", spy)
    return seen


def test_the_eval_runs_from_a_scratch_home_and_never_opens_the_live_store_to_write(live_home, tmp_path, monkeypatch):
    from harness import cli
    before = live_home.read_bytes()
    writes = _writes_to(monkeypatch, live_home)
    monkeypatch.setattr(delegate, "complete", lambda lane, p, **kw: {"text": "none", "spec": "s", "model": "m"})
    cli.main(["ask", "--eval", str(tmp_path / "ev"), "--n", "4", "--chunk", "2000"])
    assert writes == [] and live_home.read_bytes() == before
    assert (tmp_path / "ev" / "home").is_dir() and (tmp_path / "ev" / "results.jsonl").exists()


def test_the_redo_measure_runs_from_a_scratch_home(live_home, tmp_path, monkeypatch):
    from harness import cli, paths
    writes = _writes_to(monkeypatch, live_home)
    assert cli.main(["ask", "--redo", "--root", str(tmp_path)]) == 0
    assert writes == [] and not paths.is_live(paths.home() / "discovery.db")


def test_naming_the_live_home_is_refused_unless_asked_for(live_home, tmp_path, monkeypatch, capsys):
    from harness import cli, paths
    monkeypatch.setenv(paths.ENV_VAR, str(live_home.parent))
    assert cli.main(["ask", "--redo", "--root", str(tmp_path)]) == 2
    assert "--live-home" in capsys.readouterr().out
    assert cli.main(["ask", "--redo", "--root", str(tmp_path), "--live-home"]) == 0
    assert paths.is_live(paths.home() / "discovery.db")
