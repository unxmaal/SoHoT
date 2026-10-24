"""A subagent's SubagentHandback report is its census unit's result. #1162."""
import json
from datetime import datetime, timezone

from evals import redact
from evals.analysis import demand as d
from evals.analysis.demand import replay

NOW = 1_790_000_000.0
T0 = NOW - 86400
REPORT = "HANDBACK: the parser drops the trailing field; PR 12 fixes it, tests green"


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _asst(t, mid, *blocks):
    usage = {"input_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
             "output_tokens": 50}
    return {"type": "assistant", "timestamp": _iso(t), "message": {"id": mid, "usage": usage,
                                                                   "content": list(blocks)}}


def _text(s):
    return {"type": "text", "text": s}


def _use(uid, name, **args):
    return {"type": "tool_use", "id": uid, "name": name, "input": args}


def _write(path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


def _units(tmp_path):
    root = tmp_path / "projects"
    main = root / "-Users-someone-projects" / "s1.jsonl"
    _write(main, [
        {"type": "user", "timestamp": _iso(T0), "promptId": "p1", "origin": {"kind": "human"},
         "userType": "external", "message": {"role": "user", "content": "Dig into the parser"}},
        _asst(T0 + 5, "m1", _use("a1", "Agent", description="dig", prompt="dig")),
        _asst(T0 + 5, "m2", _use("a2", "Agent", description="look", prompt="look")),
        _asst(T0 + 5, "m3", _use("a3", "Agent", description="poke", prompt="poke")),
    ])
    subs = main.parent / "s1" / "subagents"
    _write(subs / "agent-aaa.jsonl", [
        {"type": "user", "timestamp": _iso(T0 + 10), "message": {"role": "user", "content": "Dig into the parser"}},
        _asst(T0 + 20, "s1", _text("Let me read the parser."), _use("b1", "Read", file_path="/x/parser.py")),
        _asst(T0 + 30, "s2", _use("h1", "SubagentHandback", message=REPORT)),
    ])
    _write(subs / "agent-bbb.jsonl", [
        {"type": "user", "timestamp": _iso(T0 + 11), "message": {"role": "user", "content": "Look at the log"}},
        _asst(T0 + 20, "s3", _use("b2", "Read", file_path="/x/log.txt")),
    ])
    _write(subs / "agent-ccc.jsonl", [
        {"type": "user", "timestamp": _iso(T0 + 12), "message": {"role": "user", "content": "Poke the cache"}},
        _asst(T0 + 20, "s4", _text("The cache is cold.")),
        _asst(T0 + 30, "s5", _use("h2", "SubagentHandback", message="  ")),
    ])
    units, _ = d.scan(root, NOW)
    return {u.stream: u for u in units if u.kind == "subagent"}


def test_a_handback_report_is_the_units_result_and_reaches_its_packet(tmp_path):
    sub = _units(tmp_path)["agent-aaa"]
    assert sub.result == REPORT
    assert d.packet(sub, "P001", redact.Known())["result"] == REPORT


def test_a_unit_without_a_handback_keeps_its_text_or_stays_empty(tmp_path):
    units = _units(tmp_path)
    assert units["agent-bbb"].result == ""
    assert d.packet(units["agent-bbb"], "P002", redact.Known())["result"] == ""
    assert units["agent-ccc"].result == "The cache is cold."


def test_census_and_replay_read_the_same_report_tools():
    assert replay.REPORT_TOOLS is d.REPORT_TOOLS
