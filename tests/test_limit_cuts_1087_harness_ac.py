"""Limits in harness/a*-c* modules record a limit_cuts row when they bind and none when they do not (#1087)."""
from __future__ import annotations

import dataclasses
import json
import socket
import sqlite3
import subprocess
import sys
import types
import urllib.error

import httpx
import pytest

from harness import cuts
from harness import memory_store as ms
from tests.test_context import GIB, ORNITH, QWEN3_4B
from tests.test_context_store import _gguf, models  # noqa: F401
from tests.test_harness_adopt import head_to_head_rows, row


_REAL: dict = {}


@pytest.fixture(autouse=True)
def _no_real_router(monkeypatch):
    """The suite's guard, keeping the real context._get_json for the one test that fakes urlopen under it."""
    from harness import context, router
    _REAL.setdefault("get_json", context._get_json)
    monkeypatch.setattr(router, "_get", lambda path: {"data": []})
    monkeypatch.setattr(context, "_get_json", lambda url, key="": {"data": []})
    monkeypatch.setattr(router, "_post", lambda path, body: {})


@pytest.fixture(autouse=True)
def _no_gateway_probe(monkeypatch):
    """The suite's guard, keeping the real probe for the one test that fakes httpx.get under it."""
    from harness import completion
    _REAL.setdefault("probe", completion._answers_as_gateway)
    monkeypatch.setattr(completion, "_answers_as_gateway", lambda base: False)


def _knobs() -> list[str]:
    """Every cut this test's home holds: spooled, or already moved into its store."""
    path = cuts._spool_path()
    got = [json.loads(line)["knob"] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    if ms.db_path().exists():
        c = sqlite3.connect(ms.db_path())
        try:
            got += [r[0] for r in c.execute("SELECT knob FROM limit_cuts ORDER BY id")]
        finally:
            c.close()
    return got


def _stored(conn) -> list[tuple]:
    return [tuple(r) for r in conn.execute("SELECT knob, kept, dropped FROM limit_cuts ORDER BY id")]


def test_a_metric_win_the_paired_alpha_refuses_is_a_cut_when_recorded(tmp_path):
    from harness import adopt
    conn = ms.connect(tmp_path / "d.db")
    ms.record(conn, ms.Seen(name="org/new", source="feeds", lane="tts", kind="weights", resolved="org/new"))
    inc, ch = row("inc", 0.05), row("ch", 0.01)
    won = adopt.decide("tts", inc, ch, head_to_head_rows([False] * 8, [True] * 8))
    lost = adopt.decide("tts", ch, inc, head_to_head_rows([True] * 8, [False] * 8))
    short = adopt.decide("tts", inc, ch, head_to_head_rows([False] * 8, [True] * 5 + [False] * 3))
    assert won.adopt and won.alpha_cut == () and lost.alpha_cut == ()
    assert not short.adopt and short.alpha_cut[1] == adopt.ALPHA
    adopt.record(conn, dataclasses.replace(lost, challenger="org/new"))
    assert _stored(conn) == []
    adopt.record(conn, dataclasses.replace(short, challenger="org/new"))
    assert [r for r in _stored(conn) if r[0] == "adopt_alpha"] == [("adopt_alpha", 0, 1)]


def test_a_by_hand_win_on_too_few_votes_is_held_as_a_cut(monkeypatch):
    from harness import adopt, human
    votes = {"n": 3}
    monkeypatch.setattr(human, "lane_verdict", lambda lane, pairs, conn=None: ("ch", "a person preferred it"))
    monkeypatch.setattr(human, "vote_stats", lambda lane, pairs, conn=None: (votes["n"], 1.0))
    assert adopt.decide_by_hand("tts", "inc", "ch", [], force=True).held == ""
    votes["n"] = adopt.MIN_VOTES
    assert adopt.decide_by_hand("tts", "inc", "ch", []).held == ""
    assert _knobs() == []
    votes["n"] = 3
    assert adopt.decide_by_hand("tts", "inc", "ch", []).held
    assert _knobs() == ["harness/adopt.py:MIN_VOTES"]


def test_the_held_and_alpha_cuts_land_whole_in_the_store_they_are_given(tmp_path, monkeypatch):
    from harness import adopt, human
    conn = ms.connect(tmp_path / "d.db")
    monkeypatch.setattr(human, "lane_verdict", lambda lane, pairs, conn=None: ("ch", "a person preferred it"))
    monkeypatch.setattr(human, "vote_stats", lambda lane, pairs, conn=None: (3, 1.0))
    assert adopt.decide_by_hand("tts", "inc", "ch", [], min_votes=5, conn=conn).held
    ms.record(conn, ms.Seen(name="org/new", source="feeds", lane="tts", kind="weights", resolved="org/new"))
    adopt.record(conn, adopt.Verdict("tts", "inc", "org/new", False, "not established", alpha_cut=(0.0312, 0.0125)))
    got = [tuple(r) for r in conn.execute("SELECT knob, value, what, kept, dropped FROM limit_cuts ORDER BY id")
           if r["knob"] in ("harness/adopt.py:MIN_VOTES", "adopt_alpha")]
    assert got == [("harness/adopt.py:MIN_VOTES", 5.0, "tts: ch held on 3 vote(s)", 0, 1),
                   ("adopt_alpha", 0.0125, "tts: org/new better on the metric at p=0.031, over alpha", 0, 1)]


def test_empty_tts_audio_is_a_cut(tmp_path, monkeypatch):
    from harness import audio
    from tests.test_harness_audio import wav_bytes
    body = {"content": wav_bytes()}
    monkeypatch.setattr(audio.httpx, "post", lambda *a, **k: httpx.Response(
        200, content=body["content"], request=httpx.Request("POST", "http://x")))
    audio.speak("hi", out=tmp_path / "a.wav", base_url="http://x/v1")
    assert _knobs() == []
    body["content"] = b""
    with pytest.raises(audio.AudioError):
        audio.speak("hi", out=tmp_path / "b.wav", base_url="http://x/v1")
    assert _knobs() == ["harness/audio.py:MIN_AUDIO_BYTES"]


def test_silent_synthesis_on_the_cuda_audio_server_is_a_cut(monkeypatch):
    pytest.importorskip("fastapi", reason="needs the `dev` group")
    from fastapi.testclient import TestClient

    from harness import audio_server
    size = {"n": audio_server.MIN_AUDIO_BYTES}

    class Kokoro:
        def __init__(self, model, voices):
            pass

        def get_voices(self):
            return ["bm_george"]

        def create(self, text, voice, speed, lang):
            return [0], 24000

    def write(buf, samples, rate, format):
        buf.write(b"x" * size["n"])

    monkeypatch.setitem(sys.modules, "kokoro_onnx", types.SimpleNamespace(Kokoro=Kokoro))
    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(write=write))
    monkeypatch.setenv("KOKORO_MODEL", "m.onnx")
    monkeypatch.setenv("KOKORO_VOICES", "v.bin")
    client = TestClient(audio_server.build_app())
    ask = {"model": audio_server.KOKORO_IDS[0], "input": "hi"}
    assert client.post("/v1/audio/speech", json=ask).status_code == 200
    assert _knobs() == []
    size["n"] = 10
    assert client.post("/v1/audio/speech", json=ask).status_code == 500
    assert _knobs() == ["harness/audio_server.py:MIN_AUDIO_BYTES"]


def test_an_audit_past_its_file_limit_is_a_cut(tmp_path):
    from harness import audit
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.py").write_text("x = 1\n", encoding="utf-8")
    assert audit.scan(tmp_path)[0].files == 3
    assert _knobs() == []
    assert audit.scan(tmp_path, limit=2)[0].files == 2
    assert _knobs() == ["harness/audit.py:scan(limit)"]


def test_a_never_passing_incumbent_on_too_few_cases_is_a_cut(monkeypatch):
    from harness import adopt, baseline, power
    draws = {"d": {}}
    monkeypatch.setattr(adopt, "current", lambda conn: {})
    monkeypatch.setattr(power, "served_profile", lambda conn, lane, spec: (draws["d"], None))
    draws["d"] = {f"c{i}": [False] for i in range(baseline.MIN_CASES)}
    assert baseline.zero_pass(None, "code", "typed")["cases"] == baseline.MIN_CASES
    draws["d"] = {"c0": [True], "c1": [False]}
    assert baseline.zero_pass(None, "code", "typed") is None
    assert _knobs() == []
    draws["d"] = {"c0": [False], "c1": [False]}
    assert baseline.zero_pass(None, "code", "typed") is None
    assert _knobs() == ["zero_pass_min_cases"]


def test_unpopular_benchmark_datasets_are_a_cut_on_both_floors():
    from harness import benchmarks as b
    popular = {"id": "org/big", "downloads": b.MIN_DOWNLOADS}
    assert [x.name for x in b._read_hf("code", lambda url, params: [popular])] == ["hf:org/big"]
    assert _knobs() == []
    quiet = {"id": "org/quiet", "downloads": 0, "likes": 0}
    assert [x.name for x in b._read_hf("code", lambda url, params: [popular, quiet])] == ["hf:org/big"]
    assert _knobs() == ["harness/benchmarks.py:MIN_DOWNLOADS", "harness/benchmarks.py:MIN_LIKES"]


def test_canary_plants_skipped_after_the_wait_are_a_cut(monkeypatch):
    from harness import canary
    monkeypatch.setattr(canary, "loop_running", lambda: True)
    monkeypatch.setattr(canary, "unsafe", lambda plant: "")
    clock = iter([0.0, 0.0, 10.0 ** 9, 10.0 ** 9])
    got = canary.run(plants=canary.PLANTS[:1], now=lambda: next(clock), sleep=lambda s: None, say=lambda s: None)
    assert got["skipped"] and _knobs() == ["canary_wait_h"]


def test_a_stale_canary_receipt_is_a_cut_and_a_fresh_or_missing_one_is_not(monkeypatch):
    from harness import canary
    receipt = {"r": None}
    monkeypatch.setattr(canary, "latest", lambda: receipt["r"])
    day = 86400.0
    assert canary.morning_line(now=canary.STALE_DAYS * day + 1)
    receipt["r"] = {"started": 0.0, "plants": [], "ok": True}
    canary.morning_line(now=day)
    assert _knobs() == []
    assert canary.morning_line(now=canary.STALE_DAYS * day + 1)
    assert _knobs() == ["canary_stale_days"]


def test_a_sweep_leaving_too_little_ceiling_to_report_is_a_cut():
    from harness import ceiling
    now = {"t": 0.0}
    sweep = ceiling.Sweep(ceiling_s=2 * ceiling.UNUSED_S, clock=lambda: now["t"], started=0.0)
    assert sweep.unused() is not None
    now["t"] = 2 * ceiling.UNUSED_S
    assert sweep.unused() is None
    now["t"] = ceiling.UNUSED_S + 60
    sweep.summary()
    assert _knobs() == []
    assert sweep.unused() is None
    assert _knobs() == ["sweep_unused_s"]


class _Proc:
    def __init__(self, waits: bool):
        self.waits, self.stdout = waits, None

    def poll(self):
        return None

    def kill(self):
        pass

    def wait(self, timeout=None):
        if not self.waits:
            raise subprocess.TimeoutExpired("server", timeout)
        return 0


def test_a_chaos_server_that_outlives_its_kill_wait_is_a_cut():
    from harness import chaos
    chaos.kill(chaos.Server("http://127.0.0.1:1/v1", _Proc(waits=True)))
    assert _knobs() == []
    chaos.kill(chaos.Server("http://127.0.0.1:1/v1", _Proc(waits=False)))
    assert _knobs() == ["harness/chaos.py:kill->server.proc.wait(timeout)"]


def test_a_chaos_probe_that_times_out_is_a_cut_and_a_refused_one_is_not(monkeypatch):
    from harness import chaos
    error = {"e": urllib.error.URLError(ConnectionRefusedError())}

    def urlopen(url, timeout):
        raise error["e"]

    monkeypatch.setattr(chaos.urllib.request, "urlopen", urlopen)
    server = chaos.Server("http://127.0.0.1:1/v1", _Proc(waits=True))
    assert not chaos.answers(server)
    assert _knobs() == []
    error["e"] = urllib.error.URLError(socket.timeout("timed out"))
    assert not chaos.answers(server)
    assert _knobs() == ["harness/chaos.py:answers->urllib.request.urlopen(timeout)"]


def test_a_chaos_server_not_back_within_its_recovery_is_a_cut(tmp_path):
    from harness import chaos
    from tests.test_chaos import server_mechanics
    ctx = chaos.Context(home=tmp_path, live=tmp_path)
    started = []
    chaos._server_kill(ctx, server_mechanics(started, alive=lambda server: True))
    assert "harness/chaos.py:ServerKill.recover_seconds" not in _knobs()
    chaos._server_kill(ctx, server_mechanics(started))
    assert "harness/chaos.py:ServerKill.recover_seconds" in _knobs()


def test_a_resetting_endpoint_thread_left_running_is_a_cut(monkeypatch):
    from harness import chaos

    class Stuck:
        def __init__(self, target, daemon):
            pass

        def start(self):
            pass

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return True

    with chaos.resetting_endpoint():
        pass
    assert _knobs() == []
    monkeypatch.setattr(chaos.threading, "Thread", Stuck)
    with chaos.resetting_endpoint():
        pass
    assert _knobs() == ["harness/chaos.py:resetting_endpoint->t.join(timeout)"]


def test_a_chaos_registry_fetch_names_its_own_retries_and_timeout(monkeypatch):
    from harness import chaos, feeds
    seen = {}
    monkeypatch.setattr(feeds, "fetch", lambda url, **kw: seen.update(kw) or "")
    chaos._registry_for("http://127.0.0.1:1")("https://huggingface.co/api/models/x")
    assert seen["retries_knob"] == "harness/chaos.py:_registry_for.fetch->feeds.fetch(retries)"
    assert seen["timeout_knob"] == "harness/chaos.py:_registry_for.fetch->feeds.fetch(timeout)"


def test_a_feed_timeout_records_under_the_knob_its_caller_names(monkeypatch):
    from harness import feeds

    def urlopen(req, timeout):
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr(feeds.urllib.request, "urlopen", urlopen)
    with pytest.raises(feeds.FeedError):
        feeds.fetch("http://127.0.0.1:1/x", retries=0, timeout_knob="harness/chaos.py:x", sleep=lambda s: None)
    assert _knobs()[0] == "harness/chaos.py:x"


def test_a_chaos_snapshot_past_its_etag_timeout_is_a_cut(monkeypatch):
    import huggingface_hub

    from harness import chaos

    def snapshot_download(**kw):
        raise TimeoutError("etag")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)
    with pytest.raises(TimeoutError):
        chaos._snapshot_for("http://127.0.0.1:1")("org/m")
    assert _knobs() == ["harness/chaos.py:_snapshot_for.snapshot->snapshot_download(etag_timeout)"]


def test_a_gateway_probe_that_times_out_is_a_cut_and_a_refused_one_is_not(monkeypatch):
    from harness import completion
    error = {"e": httpx.ConnectError("refused")}

    def get(url, timeout):
        raise error["e"]

    monkeypatch.setattr(completion.httpx, "get", get)
    monkeypatch.setattr(completion, "_answers_as_gateway", _REAL["probe"])
    assert not completion._answers_as_gateway("http://127.0.0.1:1")
    assert _knobs() == []
    error["e"] = httpx.ReadTimeout("slow")
    assert not completion._answers_as_gateway("http://127.0.0.1:1")
    assert _knobs() == ["harness/completion.py:_answers_as_gateway->httpx.get(timeout)"]


def test_a_contamination_probe_past_its_timeout_is_a_cut(monkeypatch):
    from harness import contamination, gateway_key
    monkeypatch.setattr(gateway_key, "headers", lambda: {})
    error = {"e": httpx.ConnectError("refused")}

    def post(*a, **k):
        raise error["e"]

    ask = contamination.gateway_ask("http://127.0.0.1:1", post=post)
    with pytest.raises(httpx.ConnectError):
        ask("m", "p")
    assert _knobs() == []
    error["e"] = httpx.ReadTimeout("slow")
    with pytest.raises(httpx.ReadTimeout):
        ask("m", "p")
    assert _knobs() == ["harness/contamination.py:gateway_ask.ask->post(timeout)"]


def test_a_router_api_read_past_its_timeout_is_a_cut(monkeypatch):
    from harness import context

    def urlopen(req, timeout):
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(context, "_get_json", _REAL["get_json"])
    with pytest.raises(urllib.error.URLError):
        context._get_json("http://127.0.0.1:1/models")
    assert _knobs() == ["harness/context.py:_get_json->urllib.request.urlopen(timeout)"]


def test_each_limit_that_shrinks_or_refuses_a_planned_context_is_named():
    from harness import context
    q = (QWEN3_4B, 10 * GIB, 16 * GIB, 16 * GIB)
    one = context.choose(QWEN3_4B, 10 * GIB, 16 * GIB, 1)
    assert context._bound(*q, None, 1, "f16", None, one) == ""
    assert context._bound(*q, None, 2, "f16", None, context.choose(QWEN3_4B, 10 * GIB, 16 * GIB, 2)) == "slots"
    capped = context.choose(QWEN3_4B, 10 * GIB, 16 * GIB, 1, kv_cap=GIB)
    assert context._bound(*q, None, 1, "f16", GIB, capped) == "cap"
    low = context.choose(QWEN3_4B, 15 * GIB, 16 * GIB, 1)
    assert context._bound(QWEN3_4B, 15 * GIB, 16 * GIB, 16 * GIB, None, 1, "f16", None, low) == "floor"
    plan = (ORNITH, 20 * GIB, 22 * GIB, 22 * GIB, (1, 262144), 1, "f16", None)
    assert context._bound(*plan, context._sized(*plan)[1]) == "plan"
    pool = (ORNITH, 20 * GIB, 60 * GIB, 28 * GIB, (4, 262144), 4, "f16", None)
    n, got = context._sized(*pool)
    assert n == 4 and context._bound(*pool[:5], n, "f16", None, got) == "pool"
    context._cuts(None, {"": ["a"], "floor": ["f"], "cap": ["c"], "plan": [context.ORNITH_STEM],
                         "pool": [context.EVAL_7B_STEM], "slots": ["s"]}, 4)
    assert _knobs() == ["harness/context.py:FLOOR", "kv_cap", "ornith_slot_ctx", "eval7b_slots", "llamacpp_slots"]


def test_a_recorded_plan_cuts_once_per_limit_and_a_dry_one_records_nothing(models, monkeypatch):  # noqa: F811
    from harness import context, memory
    monkeypatch.setattr(memory, "total_gb", lambda: float(context.KV_MAX_RAM_GB))
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0, raising=False)
    conn = ms.connect()
    try:
        _gguf(conn, models, "Tiny", {**QWEN3_4B, "qwen3.context_length": 4096})
        _gguf(conn, models, "Q", QWEN3_4B, repo="org/q")
        context.plan(conn, budget=60 * GIB, kv_cap=GIB, record=False)
        assert _stored(conn) == []
        context.plan(conn, budget=60 * GIB, kv_cap=1000 * GIB)
        assert [k for k, _, _ in _stored(conn)] == ["harness/context.py:FLOOR"]
        context.plan(conn, budget=60 * GIB, kv_cap=GIB)
        assert [k for k, _, _ in _stored(conn)] == ["harness/context.py:FLOOR", "harness/context.py:FLOOR", "kv_cap"]
    finally:
        conn.close()
