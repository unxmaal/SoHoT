"""`soh inventory weight --kind agents`: per-subagent tokens spent reading and re-reading files before the first edit. #1260."""
import hashlib
import json

from evals import redact
from harness import agent_weight as aw, cli, inventory_weight as iw

T0 = 1792900000.0
KNOWN = redact.Known(accounts=("someone",), names=("Zebulon",), hosts=())


def _at(i):
    import datetime
    return datetime.datetime.fromtimestamp(T0 + i, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _asst(i, mid, blocks, tokens_in=1000):
    return {"type": "assistant", "timestamp": _at(i), "cwd": "/w/repo",
            "message": {"id": mid, "content": blocks, "stop_reason": "tool_use",
                        "usage": {"input_tokens": 10, "cache_read_input_tokens": tokens_in - 10, "output_tokens": 5}}}


def _call(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _result(i, tid, chars):
    return {"type": "user", "timestamp": _at(i), "cwd": "/w/repo",
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "x" * chars}]}}


def _write(path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


def _tree(tmp_path, agent_type="sohot-fix", sub=None):
    root = tmp_path / "projects"
    spawn = _asst(1, "m0", [_call("r0", "Read", file_path="/w/repo/a.py"), _call("t0", "Agent", prompt="go")], 500)
    main = [{"type": "user", "timestamp": _at(0), "message": {"content": "do it"}}, spawn, _result(2, "r0", 4000)]
    _write(root / "-w" / "s1.jsonl", main)
    sub = sub if sub is not None else [
        spawn, _result(2, "r0", 4000),
        {"type": "user", "timestamp": _at(3), "isSidechain": True, "message": {"content": "the task"}},
        _asst(4, "m1", [_call("t1", "Read", file_path="/w/repo/a.py")], 1000), _result(5, "t1", 400),
        _asst(6, "m2", [_call("t2", "Read", file_path="/w/repo/a.py")], 1200), _result(7, "t2", 400),
        _asst(8, "m3", [_call("t3", "Bash", command="cat b.py")], 1400), _result(9, "t3", 800),
        _asst(10, "m4", [_call("t4", "Read", file_path="/w/repo/a.py", offset=100, limit=50)], 1600),
        _result(11, "t4", 40),
        _asst(12, "m5", [_call("t5", "Edit", file_path="/w/repo/a.py", old_string="a", new_string="b")], 1800),
        _result(13, "t5", 20),
        _asst(14, "m6", [_call("t6", "Read", file_path="/w/repo/b.py")], 2000), _result(15, "t6", 4000),
        _asst(16, "m7", [{"type": "text", "text": "done"}], 2200),
        _asst(17, "m7", [{"type": "text", "text": "done"}], 2200),
    ]
    s = root / "-w" / "s1" / "subagents" / "agent-a1b2c3.jsonl"
    _write(s, sub)
    s.with_name("agent-a1b2c3.meta.json").write_text(json.dumps({"agentType": agent_type}), encoding="utf-8")
    return root


def _one(tmp_path, **kw):
    got = aw.scan(_tree(tmp_path, **kw), since=0, now=T0 + 100, known=KNOWN)
    assert len(got) == 1, got
    return got[0]


def test_a_file_read_twice_before_the_first_edit_counts_its_second_read_as_a_re_read(tmp_path):
    s = _one(tmp_path)
    assert s["read"] == 100 + 100 + 200 + 10
    assert s["reread"] == 100 + 10, "the second whole read, and a range of a file already read whole"
    assert s["edited"] is True
    assert s["carried"] == 100 * 6 + 100 * 5 + 200 * 4 + 10 * 3
    assert s["carried_reread"] == 100 * 5 + 10 * 3


def test_a_forked_subagents_copy_of_the_spawning_message_is_counted_once(tmp_path):
    s = _one(tmp_path)
    assert s["messages"] == 7, "m0 belongs to the main stream; m7's two records are one message"
    assert s["input"] == 1000 + 1200 + 1400 + 1600 + 1800 + 2000 + 2200
    assert s["read"] < 1000, "the main stream's read of a.py, copied into the fork, is not the subagent's"


def test_a_read_after_the_first_edit_is_not_counted(tmp_path):
    s = _one(tmp_path)
    assert s["read"] == 410, "t6 (1000 tokens) comes after the edit"


def test_a_ranged_read_of_another_part_of_a_file_is_not_a_re_read(tmp_path):
    sub = [{"type": "user", "timestamp": _at(3), "message": {"content": "t"}},
           _asst(4, "m1", [_call("t1", "Read", file_path="/w/repo/a.py", offset=1, limit=50)]), _result(5, "t1", 40),
           _asst(6, "m2", [_call("t2", "Read", file_path="/w/repo/a.py", offset=100, limit=50)]), _result(7, "t2", 40),
           _asst(8, "m3", [_call("t3", "Read", file_path="/w/repo/a.py", offset=120, limit=11)]), _result(9, "t3", 80),
           _asst(10, "m4", [_call("t4", "Read", file_path="/w/repo/a.py")]), _result(11, "t4", 400)]
    s = _one(tmp_path, sub=sub)
    assert s["reread"] == 20, "only lines 120-130, inside 100-149, were read before; the whole read reads more"
    assert s["edited"] is False and s["read"] == 10 + 10 + 20 + 100


def test_a_bash_cat_of_a_file_counts_as_a_read(tmp_path):
    sub = [{"type": "user", "timestamp": _at(3), "message": {"content": "t"}},
           _asst(4, "m1", [_call("t1", "Bash", command="cat /w/repo/b.py")]), _result(5, "t1", 800),
           _asst(6, "m2", [_call("t2", "Bash", command="sed -n '1,40p' b.py && head -n 5 c.py")]), _result(7, "t2", 400),
           _asst(8, "m3", [_call("t3", "Bash", command="ls -la /w/repo")]), _result(9, "t3", 4000),
           _asst(10, "m4", [_call("t4", "Bash", command="make check > /dev/null 2>&1")]), _result(11, "t4", 40),
           _asst(10, "m4b", [_call("t4b", "Bash", command="make check > tmp/1260.x/check.log 2>&1")]),
           _result(11, "t4b", 40),
           _asst(10, "m4c", [_call("t4c", "Bash", command="git fetch -q && git checkout -q -b x origin/main")]),
           _result(11, "t4c", 40),
           _asst(10, "m4d", [_call("t4d", "Bash", command="uv run python - <<'EOF'\nprint(3 > 2)\nEOF")]),
           _result(11, "t4d", 40),
           _asst(12, "m5", [_call("t5", "Bash", command="cat b.py")]), _result(13, "t5", 800),
           _asst(14, "m6", [_call("t6", "Bash", command="cat > d.py <<'EOF'\nx = 1\nEOF")]), _result(15, "t6", 4),
           _asst(16, "m7", [_call("t7", "Bash", command="cat b.py")]), _result(17, "t7", 800)]
    s = _one(tmp_path, sub=sub)
    assert s["read"] == 200 + 100 + 200, ("ls is not a file read; a log redirect or a new branch is not an edit; "
                                          "the heredoc is")
    assert s["reread"] == 200, "cat b.py after cat /w/repo/b.py from /w/repo is the same file"
    assert s["edited"] is True


def test_the_agents_report_names_no_path_and_prints_tokens_not_dollars(tmp_path, monkeypatch):
    subs = [_one(tmp_path / "a"), _one(tmp_path / "b", agent_type="~/agents/x"),
            _one(tmp_path / "c", agent_type="Zebulon-helper"), _one(tmp_path / "d", agent_type="two words")]
    assert [s["type"] for s in subs] == ["sohot-fix", "other", "other", "other"]
    L = iw.build({"now": T0 + 100, "since": 0, "agents": {"subagents": subs}})
    k = L["kinds"]["agents"]
    rows = {r["name"]: r for r in k["rows"]}
    assert set(rows) == {"sohot-fix", "other"} and rows["other"]["subagents"] == 3
    assert rows["sohot-fix"]["reread"] == 110 and rows["sohot-fix"]["input"] == 11200
    assert not any(r["flagged"] or r["load_bearing"] for r in k["rows"]), "agent tokens are not a part to cut"
    out = iw.render(L) + json.dumps(L)
    assert "re-read" in out and "/w/repo" not in out and "a.py" not in out and "Zebulon" not in out
    assert "$" not in out and "usd" not in out.lower() and "dollar" not in out.lower()
    assert "agent-a1b2c3" not in iw.render(L)


def _snapshot(root):
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_transcripts_are_only_read(tmp_path, monkeypatch, capsys):
    root = _tree(tmp_path)
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(root))
    monkeypatch.setattr(redact, "known_here", lambda *a: KNOWN)
    from harness import memory_store as ms
    ms.connect().close()
    before = _snapshot(root)
    assert cli.main(["inventory", "weight", "--json", "--no-ci", "--kind", "agents", "--since", "2026-01-01"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kinds"]["agents"]["rows"][0]["name"] == "sohot-fix"
    assert _snapshot(root) == before
    assert list(root.parent.iterdir()) == [root], "nothing written beside the transcripts"


def test_the_kinds_the_command_offers_are_the_kinds_the_inventory_builds():
    import argparse

    def actions(p):
        for a in p._actions:
            yield a
            if isinstance(a, argparse._SubParsersAction):
                for sub in a.choices.values():
                    yield from actions(sub)
    kind = next(a for a in actions(cli.build_parser())
                if "--kind" in a.option_strings and a.default is None and a.choices and "agents" in a.choices)
    assert tuple(kind.choices) == iw.KINDS


def test_a_headless_session_is_left_out(tmp_path):
    root = _tree(tmp_path)
    main = root / "-w" / "s1.jsonl"
    recs = [json.loads(x) for x in main.read_text(encoding="utf-8").splitlines()]
    recs[0]["entrypoint"] = "sdk-cli"
    _write(main, recs)
    assert aw.scan(root, since=0, now=T0 + 100, known=KNOWN) == [], "a claude -p eval run is not one of our agents"


def test_a_subagent_outside_the_window_is_left_out(tmp_path):
    root = _tree(tmp_path)
    assert aw.scan(root, since=T0 + 50, now=T0 + 100, known=KNOWN) == []
    assert aw.scan(root, since=0, now=T0 + 1, known=KNOWN) == []
