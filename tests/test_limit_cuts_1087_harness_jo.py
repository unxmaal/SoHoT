"""harness/j*.py to harness/o*.py limits record a limit_cuts row when they bind, and none when they do not (#1087)."""
from __future__ import annotations

import json
import subprocess
from datetime import timezone

import pytest

from harness import cuts


def _spooled() -> list[tuple]:
    path = cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]


def _knobs() -> list[str]:
    return [k for k, _, _ in _spooled()]


def _timeout(*a, **kw):
    raise subprocess.TimeoutExpired(a[0] if a else "x", kw.get("timeout") or 1)


def test_a_mentions_reply_past_the_cap_is_one_cut_per_thread(monkeypatch):
    from harness import judge
    monkeypatch.setattr(judge, "MAX_MENTIONS", 2)
    monkeypatch.setattr(judge, "MENTION_CHUNK_CHARS", 20)
    reply = "\n".join(f"tool{i} | does {i}" for i in range(5))
    got = judge.mentions("word " * 8, complete=lambda *a, **k: reply)
    assert [n for n, _ in got] == ["tool0", "tool1"]
    assert _spooled() == [("max_mentions", 2, 6)]


def test_a_mentions_reply_inside_the_cap_is_no_cut():
    from harness import judge
    got = judge.mentions("a thread", complete=lambda *a, **k: "tool0 | does it\ntool1 | too")
    assert len(got) == 2 and _spooled() == []


def test_fields_the_label_threshold_leaves_out_of_the_blind_check_are_one_cut():
    from harness import label
    items = [{"id": i, "schema": {"a": {}, "b": {}}} for i in range(3)]
    labels = [{"id": i, "answers": {"a": "x", "b": "y"}, "probs": {"a": {"x": 0.95}, "b": {"y": 0.5}}}
              for i in range(3)]
    got = label.select(items, labels)
    assert [list(t["schema"]) for t in got] == [["b"]] * 3
    assert _spooled() == [("harness/label.py:select(threshold)", None, 3)]
    label.select(items, labels, threshold=1.0)
    assert len(_spooled()) == 1


class Sender:
    def __init__(self, got):
        self.got = got

    def start(self, lane, url, headers, body, hold):
        return lane

    def collect(self, handle, wait):
        return self.got[handle]


def _wake(monkeypatch, got):
    from harness import lane_probe as lp
    monkeypatch.setattr(lp, "prepare", lambda lane, sender, **kw: (
        {"lane": lane, "reason": "", "error": "", "http_status": None},
        {"url": "http://x", "headers": {}, "body": {}, "gateway": True}))
    return lp.wake(None, 0.0, lanes=list(got), sender=Sender(got))


def _reply(content, tokens):
    return {"status": 200, "seconds": 0.1, "body": json.dumps(
        {"choices": [{"message": {"content": content}}], "usage": {"completion_tokens": tokens}})}


def test_a_wake_records_one_cut_for_slow_lanes_and_one_for_replies_at_their_allowance(monkeypatch):
    from harness import lane_probe as lp
    rows = _wake(monkeypatch, {"code": None, "web": None, "decide": _reply('{"answer": "A"}', lp.max_tokens("decide"))})
    assert [r["outcome"] for r in rows] == [lp.SLOW, lp.SLOW, lp.UP]
    assert _spooled() == [("lane_probe_timeout", 1, 2), ("lane_probe_max_tokens", 2, 1)]


def test_a_wake_whose_probes_answer_inside_their_limits_is_no_cut(monkeypatch):
    rows = _wake(monkeypatch, {"code": _reply("OK", 1), "decide": _reply('{"answer": "A"}', 5)})
    assert {r["outcome"] for r in rows} == {"up"} and _spooled() == []


def test_a_probe_request_held_past_its_hold_is_a_cut(monkeypatch):
    import urllib.request

    from harness import lane_probe as lp

    def slow(*a, **kw):
        raise TimeoutError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", slow)
    got = lp._send({"url": "http://x/v1", "body": {}, "hold": 5.0})
    assert got["timed_out"] and _spooled() == [("lane_probe_hold", 0, 1)]


def _power(at, watts=100.0, cpu=10.0):
    return {"at": at, "watts": watts, "cpu_power": cpu, "cpu_active_ratio": 0.5}


NOON = 1_800_020_000.0


def test_power_gaps_implausible_readings_and_partial_days_are_each_one_cut():
    from harness import ledger
    clean = [_power(NOON + 60 * i) for i in range(10)]
    ledger.energy(clean, 0, 0.15, True, timezone.utc)
    assert _spooled() == []
    odd = [_power(NOON + 60 * i, cpu=0.0) for i in range(10)]
    odd += [_power(NOON + 60 * 9 + 1000, cpu=0.0), _power(NOON + 60 * 9 + 1010, watts=1e6, cpu=0.0)]
    out = ledger.energy(odd, 0, 0.15, True, timezone.utc)
    assert out["gaps"] == 1 and out["implausible"] == 1 and out["partial"]
    assert _spooled() == [("ledger_power_gap", None, 1), ("ledger_power_ceiling", None, 1),
                          ("ledger_cpu_unread_share", 0, 1)]


def test_a_macmon_reading_that_times_out_is_a_cut():
    from harness import ledger
    got = ledger.sample_power(runner=_timeout, which=lambda _: "/bin/macmon")
    assert not got["ok"] and _spooled() == [("ledger_power_window", 0, 1)]
    ledger.sample_power(runner=lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""), which=lambda _: "/x")
    assert len(_spooled()) == 1


def _msg(at):
    return {"at": at, "session": "s", "model": "m", "input": 1, "output": 2, "cache_read": 0, "cache_write": 0}


def test_a_transcript_message_counted_as_exported_only_by_the_slack_is_a_cut():
    from harness import ledger
    t = NOON
    events = [{"name": "api_request", "session_id": "s", "at": t, "duration_ms": 1000, "model": "m"}]
    day = ledger.day_of(t, timezone.utc)
    ledger.cloud_days([day], {}, events, [_msg(t - 0.5), _msg(t + 600)], timezone.utc)
    assert _spooled() == []
    ledger.cloud_days([day], {}, events, [_msg(t - 0.5), _msg(t + 30), _msg(t + 600)], timezone.utc)
    assert _spooled() == [("ledger_span_slack", None, 1)]


def test_lanes_with_too_few_requests_to_judge_are_one_cut(monkeypatch):
    from harness import live_audit, usage
    monkeypatch.setattr(usage, "drop_warning", lambda conn, since: [])
    use = {"code": {"requests": 3, "error_rate": 0.5}, "web": {"requests": 2, "error_rate": 0.0},
           "decide": {"requests": 500, "error_rate": 0.5}}
    monkeypatch.setattr(usage, "real_use", lambda conn: use)
    assert len(live_audit._gateway_errors(None)) == 1
    assert _spooled() == [("harness/live_audit.py:MIN_REQUESTS", None, 2)]


def test_a_look_that_stops_for_futility_is_a_cut_and_one_that_continues_is_not():
    from harness import looks
    go = looks.Look(1, 0.5, 2, 1, 0.01, 0.01, 0.6, "continue", "")
    looks.stopped(go, "code", 40, 100)
    assert _spooled() == []
    looks.stopped(looks.Look(2, 0.5, 1, 4, 0.01, 0.01, 0.02, "futility", ""), "code", 40, 100)
    assert _spooled() == [("futility_cp", 40, 60)]


def _unstubbed(module, monkeypatch):
    """A fresh copy of `module`, past conftest's stubs of its probes."""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(f"{module.__name__}_fresh", module.__file__)
    fresh = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, fresh)
    spec.loader.exec_module(fresh)
    return fresh


def test_machine_probes_that_time_out_are_cuts(monkeypatch):
    from harness import machine
    fresh = _unstubbed(machine, monkeypatch)
    monkeypatch.setattr(subprocess, "run", _timeout)
    assert fresh._mflux_cli() == ""
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    monkeypatch.setattr(machine, "_UUID", None)
    monkeypatch.setattr(machine, "_UUID_FAILED_AT", None)
    assert machine._platform_uuid() == ""
    assert _knobs() == ["harness/machine.py:_mflux_cli->subprocess.run(timeout)",
                        "harness/machine.py:_platform_uuid->subprocess.run(timeout)"]


def test_memory_probes_that_time_out_are_cuts(monkeypatch):
    from harness import memory
    monkeypatch.setattr(subprocess, "run", _timeout)
    monkeypatch.setattr(memory, "_meminfo_available_gb", lambda: 1.0)
    assert memory._unified_total_gb() == 0.0
    assert memory._discrete() is None
    assert memory.available_gb() == 1.0
    assert _knobs() == ["harness/memory.py:_unified_total_gb->subprocess.run(timeout)",
                        "harness/memory.py:_discrete->subprocess.run(timeout)",
                        "harness/memory.py:available_gb->subprocess.run(timeout)",
                        "harness/memory.py:_discrete->subprocess.run(timeout)"]


def _machine(monkeypatch, need, free, total, ceiling):
    from harness import memory
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: need)
    monkeypatch.setattr(memory, "available_gb", lambda: free)
    monkeypatch.setattr(memory, "total_gb", lambda: total)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: ceiling)
    return memory


def test_a_model_the_gpu_fraction_refuses_is_a_cut(monkeypatch):
    memory = _machine(monkeypatch, 10.0, 20.0, 12.0, 12.0 * 0.75)
    monkeypatch.setattr(memory, "GPU_FRACTION", 0.75)
    assert memory.check_model("m", reserve_gb=0.5)[0] is False
    assert _spooled() == [("gpu_fraction", 0, 1)]
    assert memory.check_model("m", reserve_gb=12.0)[0] is False
    _machine(monkeypatch, 5.0, 20.0, 12.0, 9.0)
    assert memory.check_model("m", reserve_gb=0.5)[0] is True
    assert len(_spooled()) == 1


def test_a_model_the_reserve_floor_refuses_is_a_cut(monkeypatch):
    memory = _machine(monkeypatch, 9.0, 20.0, 100.0, 9.5)
    assert memory.check_model("m", reserve_gb=memory.MIN_RESERVE_GB)[0] is False
    assert _spooled() == [("harness/memory.py:MIN_RESERVE_GB", 0, 1)]
    _machine(monkeypatch, 8.0, 20.0, 100.0, 9.5)
    assert memory.check_model("m", reserve_gb=memory.MIN_RESERVE_GB)[0] is True
    assert len(_spooled()) == 1


def test_a_swap_off_a_model_that_times_out_is_a_cut():
    import io
    import socket

    from harness import mlx_server

    def opener(req, timeout):
        if isinstance(req, str):
            return io.BytesIO(json.dumps({"model": "a/model"}).encode())
        raise socket.timeout("timed out")
    said = []
    assert not mlx_server.release("a/model", "t", base="http://mlx.test", keep=set(), opener=opener, say=said.append)
    assert "could not unload" in said[0]
    assert _spooled() == [("mlx_swap_timeout", 0, 1)]


def _gh(created):
    def gh(argv):
        if argv[:2] == ["run", "list"]:
            return json.dumps([{"databaseId": 7, "status": "completed", "conclusion": "success",
                                "createdAt": created, "headSha": "abc", "url": "u"}])
        return json.dumps({"jobs": []})
    return gh


def test_a_nightly_run_too_old_to_notify_is_a_cut():
    from datetime import datetime, timezone

    from harness import morning
    now = datetime(2026, 10, 31, 6, tzinfo=timezone.utc).timestamp()
    assert morning.ci(now, gh=_gh("2026-10-31T03:00:00Z"))["fresh"]
    assert _spooled() == []
    assert not morning.ci(now, gh=_gh("2026-10-25T03:00:00Z"))["fresh"]
    assert _spooled() == [("morning_ci_fresh", 0, 1)]


def _stall(name, lane, rank, days):
    return {"name": name, "lane": lane, "lane_rank": rank, "stage": "ranked", "in_state_days": days,
            "age_days": days, "reason": "", "why": ""}


def test_the_morning_stall_line_records_what_its_head_and_its_days_leave_out(monkeypatch):
    from harness import funnel, lanes, morning
    lane = lanes.canonical(sorted(lanes.WANTED)[0])
    rows = [_stall("a", lane, 1, 30.0), _stall("b", lane, 2, 30.0)]
    monkeypatch.setattr(funnel, "proposals", lambda conn: rows)
    assert [r["name"] for r in morning.stalled(None, days=14.0, head=2)] == ["a", "b"]
    assert _spooled() == []
    rows += [_stall("c", lane, 3, 30.0), _stall("d", lane, 1, 1.0)]
    assert [r["name"] for r in morning.stalled(None, days=14.0, head=2)] == ["a", "b"]
    assert _spooled() == [("morning_stall_head", 2, 1), ("morning_stall_days", 2, 1)]


FIELD = {"type": "boolean", "description": "Is it urgent?"}


def test_a_needle_field_that_times_out_is_a_cut(monkeypatch, tmp_path):
    from harness import needle, proc
    monkeypatch.setattr(proc, "run", _timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        needle.ask_field(needle.parse("needle:needle3"), ["needle"], "w", "urgent", FIELD, "t", "c", tmp_path)
    assert _knobs() == ["harness/needle.py:FIELD_TIMEOUT_S"]


class Stuck:
    def post(self, path, body, timeout):
        raise TimeoutError("timed out")

    def close(self):
        pass


def test_a_needle_agent_turn_that_times_out_is_a_cut(tmp_path):
    from harness import completion, needle
    chat = needle.Chat(needle.parse("needle:needle3"), ["needle"], "w", tmp_path)
    chat.server, chat.key = Stuck(), json.dumps([[], ""], sort_keys=True)
    with pytest.raises(completion.CompletionError):
        chat([{"role": "user", "content": "hi"}], timeout=3.0)
    assert _spooled() == [("harness/needle.py:Chat.__call__(timeout)", 0, 1)]


def _github(tmp_path, **kw):
    from harness import github
    from tests.test_harness_neighbors import FakeAPI
    return github.Client(cache=tmp_path / "c", runner=FakeAPI(**kw), budget=10_000)


def test_a_crowd_records_each_cap_that_left_someone_out(tmp_path):
    from harness import neighbors as nb
    client = _github(tmp_path, contributors={"o/r": ["a", "b", "c"], "o/s": ["d", "e"]})
    got = nb.cohort(["o/r", "o/s"], client, per_repo=2, follow=False, limit=3)
    assert got == ["a", "b", "d"]
    assert _spooled() == [("crowd_limit", 3, 1), ("per_repo", None, 1)]


def test_a_crowd_still_growing_at_its_last_hop_and_a_high_degree_floor_are_cuts(tmp_path):
    from harness import neighbors as nb
    client = _github(tmp_path, contributors={"o/r": ["a", "b"]}, following={"a": ["x"], "b": ["x"], "x": ["y"]})
    assert nb.cohort(["o/r"], client, per_repo=5, hops=1, limit=50, per_hop=10) == ["a", "b", "x"]
    assert _knobs() == ["hops"]
    assert nb.cohort(["o/r"], client, per_repo=5, hops=2, limit=50, min_degree=2, per_hop=10) == ["a", "b", "x"]
    assert _knobs() == ["hops", "min_degree"]


def test_a_crowd_inside_every_cap_is_no_cut(tmp_path):
    from harness import neighbors as nb
    client = _github(tmp_path, contributors={"o/r": ["a"]}, following={"a": ["x"]})
    assert nb.cohort(["o/r"], client, per_repo=5, hops=2, limit=50) == ["a", "x"]
    assert _spooled() == []


def test_repos_too_few_of_the_crowd_starred_are_one_cut(tmp_path):
    from harness import neighbors as nb
    repos = {r: {"stargazers_count": 10, "pushed_at": "2026-10-01"} for r in ("o/one", "o/two", "o/three")}
    client = _github(tmp_path, repos=repos,
                     starred={"a": ["o/one", "o/two", "o/three"], "b": ["o/one", "o/two"], "c": ["o/one"]})
    got = nb.neighbors(["a", "b", "c"], client, min_shared=2)
    assert {n.repo for n in got} == {"o/one", "o/two"}
    assert _spooled() == [("min_shared", 2, 1)]


def test_a_delegation_reply_at_its_token_budget_is_a_cut(monkeypatch):
    mcp_server = pytest.importorskip("harness.mcp_server")
    from harness import delegations

    def reply(tokens):
        return lambda *a, **kw: {"text": "x", "lane": "code", "spec": "s", "model": "m", "ttft_s": 0.1, "seconds": 1.0,
                                 "prompt_tokens": 3, "completion_tokens": tokens, "method": None, "call_id": "c1"}
    monkeypatch.setattr(delegations, "instruction", lambda call_id: "")
    monkeypatch.setattr(mcp_server.delegate, "complete", reply(10))
    mcp_server.local_complete(prompt="p", max_tokens=64)
    assert _spooled() == []
    monkeypatch.setattr(mcp_server.delegate, "complete", reply(64))
    mcp_server.local_complete(prompt="p", max_tokens=64)
    assert _spooled() == [("harness/mcp_server.py:_prompted(max_tokens)", 0, 1)]


def test_a_hostname_lookup_that_times_out_is_a_cut(monkeypatch):
    mcp_server = pytest.importorskip("harness.mcp_server")
    monkeypatch.setattr(subprocess, "run", _timeout)
    assert mcp_server._local_hostname()
    assert _knobs() == ["harness/mcp_server.py:_local_hostname->subprocess.run(timeout)"]
