"""A timeout we chose is our limit, not the candidate's failure: every timeout path is classed TIMEOUT and names its knob (#693)."""
import subprocess
import sys

import httpx
import pytest

from evals.core import Case, score
from evals.runners.base import BaseRunner
from harness import binding, knobs, paired, reasons, runs
from harness import memory_store as ms
from harness.checks import code as code_check
from harness.engines import Engine
from tests.gauntlet import scanners

SLEEPER = "import time\ntime.sleep(30)\n"


def engine(**over):
    kw = dict(name="fake", spec="fake:1", argv=lambda p, out, params: [sys.executable, "-c", "pass"],
              modality="image", output_suffix=".png", timeout=900.0)
    kw.update(over)
    return Engine(**kw)


def expired(*a, **kw):
    raise subprocess.TimeoutExpired(a[0] if a else "x", kw.get("timeout") or 1)


# ---- audio ----

def test_a_tts_timeout_is_timeout_naming_the_audio_knob(tmp_path, monkeypatch):
    from evals.runners.speech import SpeechRunner
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
    r = SpeechRunner(model="m/k", outdir=tmp_path, voice="am_adam", timeout=7.0)
    row = r.run(Case(id="p", modality="tts", prompt="hello there", assertions={"max_wer": 0.2}))
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "audio_timeout_s>7")


def test_an_stt_timeout_is_timeout_naming_the_audio_knob(tmp_path, monkeypatch):
    from evals.runners.transcription import TranscriptionRunner
    clip = tmp_path / "a.wav"
    clip.write_bytes(b"RIFF")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
    row = TranscriptionRunner(model="m/p").run(Case(id="p", modality="stt", prompt="", audio=clip))
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, f"audio_timeout_s>{knobs.KNOBS['audio_timeout'].default('stt'):g}")


# ---- the code check ----

def test_a_code_check_timeout_is_timeout_not_a_wrong_answer():
    got = code_check.check(SLEEPER + "def f():\n    return 1\n", ["f() == 1"], timeout=0.5)
    assert not got.ok
    assert (got.failure_class, got.limit) == (reasons.TIMEOUT, "code_check_timeout_s>0.5")


def test_a_code_case_may_name_its_own_check_timeout_and_the_row_carries_it():
    case = Case(id="slow", modality="code", prompt="", params={"check_timeout": 0.5},
                assertions={"checks": ["f() == 1"]})
    row = score(case, SLEEPER + "def f():\n    return 1\n")
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "code_check_timeout_s>0.5")


def test_the_code_check_timeout_is_a_registered_knob_read_at_call_time(monkeypatch):
    assert knobs.KNOBS["code_check_timeout"].default("code") == code_check.DEFAULT_TIMEOUT
    monkeypatch.setattr(code_check, "DEFAULT_TIMEOUT", 0.5)
    got = code_check.check(SLEEPER + "def f():\n    return 1\n", ["f() == 1"])
    assert got.limit == "code_check_timeout_s>0.5"


# ---- process, chain and trace runners ----

def test_a_process_timeout_names_the_engine_knob_for_its_lane(tmp_path, monkeypatch):
    from evals.runners import process
    monkeypatch.setattr(process.proc, "run", expired)
    row = process.ProcessRunner(engine(), tmp_path).run(Case(id="c", modality="image", prompt="a fox"))
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "engine_timeout_s.image>900")


def test_a_chain_stage_timeout_is_a_row_not_an_abort(tmp_path, monkeypatch):
    from evals.runners import chain
    monkeypatch.setattr(chain.stages, "stage_unavailable", lambda stage: "")
    monkeypatch.setattr(chain.proc, "run", expired)
    r = chain.ChainRunner(engine(), "upscale-seedvr2", tmp_path, timeout=1800.0)
    row = r.run(Case(id="c", modality="image", prompt="a fox", params={"width": 64, "height": 64}))
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "engine_timeout_s.image>1800")


def test_a_trace_timeout_is_a_row_not_an_abort(tmp_path, monkeypatch):
    from evals.runners import trace
    monkeypatch.setattr(trace.proc, "run", expired)
    row = trace.TraceRunner(engine(), tmp_path).run(Case(id="c", modality="svg", prompt="a fox"))
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "engine_timeout_s.svg>900")


# ---- needle ----

def test_a_needle_socket_timeout_is_timeout_on_the_request_timeout(tmp_path, monkeypatch):
    from harness import completion, needle

    class Slow:
        def post(self, path, body, timeout):
            raise TimeoutError("timed out")

        def close(self):
            pass

    chat = needle.Chat(needle.Spec("needle:x", "x"), [], "", tmp_path)
    monkeypatch.setattr(needle.Chat, "_start", lambda self, tools, system: setattr(self, "server", Slow()))
    with pytest.raises(completion.CompletionError) as got:
        chat([{"role": "user", "content": "hi"}], timeout=42.0)
    assert (got.value.failure_class, got.value.limit) == (reasons.TIMEOUT, ("timeout_s", 42.0))


def test_a_needle_serve_that_never_reports_its_address_is_timeout_on_the_start_knob(tmp_path, monkeypatch):
    from harness import completion, needle
    monkeypatch.setattr(needle, "SERVE_START_S", 0.3)
    monkeypatch.setattr(needle, "serve_argv", lambda *a, **kw: [sys.executable, "-c", "import time; time.sleep(30)"])
    chat = needle.Chat(needle.Spec("needle:x", "x"), [], "", tmp_path)
    try:
        with pytest.raises(completion.CompletionError) as got:
            chat([{"role": "user", "content": "hi"}], timeout=5.0)
    finally:
        chat.close()
    assert (got.value.failure_class, got.value.limit) == (reasons.TIMEOUT, ("needle_serve_start_s", 0.3))


# ---- claude -p ----

def test_a_claude_code_timeout_is_timeout_not_the_reference_crashing():
    from evals.runners.claude_code import ClaudeCodeRunner
    r = ClaudeCodeRunner("m", timeout=600.0, execute=expired)
    row = r.run(Case(id="add", modality="code", prompt="Write add.", assertions={"checks": ["add(1, 2) == 3"]}))
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "claude_code_timeout_s>600")


# ---- the MCP server ----

def test_an_mcp_run_lh_timeout_is_a_tool_error_naming_the_timeout(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    from harness import mcp_server
    monkeypatch.setattr(mcp_server.subprocess, "run", expired)
    with pytest.raises(ToolError, match="timed out after 300s"):
        mcp_server.run_lh([*mcp_server.LH, "code", "x"])


# ---- the paired gate ----

def _row(case_id, passed, cls=""):
    return {"candidate": "m", "case_id": case_id, "passed": passed, "failure_class": cls}


def test_a_timeout_cell_is_neither_lost_nor_gained_and_is_counted_apart():
    before = [_row("a", True), _row("b", True), _row("c", False)]
    after = [_row("a", False, reasons.TIMEOUT), _row("b", False, reasons.CONTENT_FAILED), _row("c", True)]
    cell, = paired.cells(before, after)
    assert (cell.lost, cell.gained, cell.unchanged, cell.unjudged) == (1, 1, 0, 1)


def test_a_timeout_in_a_head_to_head_is_neither_lost_nor_gained():
    rows = [{"candidate": "i", "case_id": "a", "passed": True},
            {"candidate": "c", "case_id": "a", "passed": False, "failure_class": reasons.TIMEOUT},
            {"candidate": "i", "case_id": "b", "passed": True},
            {"candidate": "c", "case_id": "b", "passed": False, "failure_class": reasons.CONTENT_FAILED}]
    cell = paired.head_to_head(rows, "i", "c")
    assert (cell.lost, cell.gained, cell.unjudged) == (1, 0, 1)


# ---- binding ----

M = {"fingerprint": "Mac17,15/macOS/arm64", "hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit",
     "arch": "arm64", "memory_gb": 96.0, "accelerator": "unified 96GB", "runtimes": "cpu,mlx",
     "ceiling_gb": 66.0, "versions": {}}


def test_binding_sees_the_code_check_timeout_bind_on_a_run(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "this_machine", lambda: dict(M))
    conn = ms.connect(tmp_path / "d.db")
    ms.remember_machine(conn, dict(M))
    now = 1_800_000_000.0

    class Slow(BaseRunner):
        candidate = "m"

        def generate(self, case):
            return SLEEPER + "def f():\n    return 1\n", 0

    case = Case(id="slow", modality="code", prompt="", params={"check_timeout": 0.5},
                assertions={"checks": ["f() == 1"]})
    hit = Slow().run(case)
    rows = [{"candidate": "m", "case_id": hit.case_id, "passed": hit.passed, "seconds": 1.0,
             "failure_class": hit.failure_class, "limit": hit.limit}]
    env = {"hw_model": M["hw_model"], "os": M["os"], "arch": "arm64"}
    runs.record(conn, "runs/r1-code", {"receipt": {"modality": "code"}, "environment": env,
                                       "specs": {"m": "m"}, "rows": rows}, at=now - 86400.0)
    got = next(r for r in binding.count(conn, now=now) if r["knob"] == "code_check_timeout" and r["lane"] == "code")
    conn.close()
    assert (got["hits"], got["of"]) == (1, 1)


# ---- the scanner that holds this at zero ----

def test_a_timeout_raised_without_its_class_is_found():
    bad = ("try:\n    go()\nexcept subprocess.TimeoutExpired as exc:\n"
           "    raise RunnerError(f'timed out') from exc\n")
    good = ("try:\n    go()\nexcept subprocess.TimeoutExpired as exc:\n"
            "    raise RunnerError('timed out', failure_class=reasons.TIMEOUT) from exc\n"
            "try:\n    go()\nexcept httpx.TimeoutException as exc:\n"
            "    raise CompletionError('timed out', reasons.TIMEOUT, ('timeout_s', 1)) from exc\n"
            "try:\n    go()\nexcept OSError as exc:\n    raise RunnerError('gone') from exc\n")
    assert scanners.unclassed_timeouts(good, "m.py") == []
    assert scanners.unclassed_timeouts(good + bad, "m.py") != []


def test_no_timeout_is_raised_without_its_class():
    from pathlib import Path

    from harness import repo
    root = Path(__file__).resolve().parent.parent
    found = []
    for path in repo.publishable(root):
        rel = path.relative_to(root).as_posix()
        if rel.endswith(".py") and rel.startswith(("harness/", "evals/")) and path.is_file():
            found += scanners.unclassed_timeouts(path.read_text(encoding="utf-8"), rel)
    assert not found, "\n  ".join(found)


# ---- review round 2 ----

def _clip(tmp_path):
    from harness.checks import speech as speech_check
    clip = tmp_path / "a.wav"
    clip.write_bytes(b"\0" * (speech_check.MIN_AUDIO_BYTES + 10))
    return clip


def _slow_ear(path):
    from harness import audio
    raise audio.AudioTimeout("stt", 120.0)


def test_a_tts_read_back_timeout_is_timeout_not_a_wrong_answer(tmp_path):
    from evals import core
    case = Case(id="p", modality="tts", prompt="hello there", assertions={"max_wer": 0.2})
    row = score(case, str(_clip(tmp_path)), transcriber=_slow_ear)
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "audio_timeout_s>120")
    assert core._check_tts(str(_clip(tmp_path)), case, transcriber=_slow_ear).failure_class == reasons.TIMEOUT


def test_a_music_read_back_timeout_is_timeout_not_a_wrong_answer(tmp_path):
    case = Case(id="m", modality="music", prompt="", params={"lyrics": "la la la", "duration": 5},
                assertions={"max_wer": 0.5})
    row = score(case, str(_clip(tmp_path)), transcriber=_slow_ear)
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "audio_timeout_s>120")


def test_a_whisperkit_or_fluidaudio_timeout_is_an_audio_timeout(tmp_path, monkeypatch):
    from harness import audio
    clip = _clip(tmp_path)
    monkeypatch.setattr(subprocess, "run", expired)
    for run in (audio.transcribe_whisperkit, audio.transcribe_fluidaudio):
        with pytest.raises(audio.AudioTimeout) as got:
            run(clip, timeout=9.0)
        assert got.value.limit == ("audio_timeout_s", 9.0)


def test_a_local_transcriber_with_no_timeout_runs_at_the_audio_knob(tmp_path, monkeypatch):
    from harness import audio
    seen = []
    monkeypatch.setattr(audio, "TIMEOUT_S", 33.0)
    monkeypatch.setattr(audio, "_run_whisperkit", lambda argv, timeout: seen.append(timeout) or "hi")
    clip = _clip(tmp_path)
    audio.transcriber("whisperkit")(clip)
    with pytest.raises(audio.AudioError):
        audio.transcriber("fluidaudio")(clip)
    assert seen == [33.0, 33.0]


def test_a_claude_agent_timeout_is_timeout_on_the_agent_case_knob(monkeypatch):
    from evals.runners import agent, claude_agent
    monkeypatch.setattr(agent, "setup", lambda case: (type("Box", (), {"cleanup": lambda self: None,
                                                                         "root": "/x"})(), "go"))
    r = claude_agent.ClaudeAgentRunner("m", timeout=900.0, execute=expired)
    row = r.run(Case(id="a", modality="agent", prompt="", params={"tools": ["read"], "max_steps": 8}))
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "agent_case_timeout_s>900")


def test_the_claude_code_timeout_is_a_registered_knob_read_at_call_time(monkeypatch):
    from evals.runners import claude_code
    assert knobs.KNOBS["claude_code_timeout"].default("code") == claude_code.TIMEOUT_S
    monkeypatch.setattr(claude_code, "TIMEOUT_S", 5.0)
    row = claude_code.ClaudeCodeRunner("m", execute=expired).run(
        Case(id="add", modality="code", prompt="Write add.", assertions={"checks": ["add(1, 2) == 3"]}))
    assert row.limit == "claude_code_timeout_s>5"


def test_every_timeout_limit_a_row_can_carry_names_a_registered_knob():
    have = reasons.limits()
    assert "claude_code_timeout_s" in have
    assert have["needle_serve_start_s"] == knobs.KNOBS["needle_serve_start"].default()


def test_a_harness_failure_cell_is_neither_lost_nor_gained():
    before = [_row(c, True) for c in "abcd"]
    after = [_row("a", False, reasons.HARNESS_ERROR), _row("b", False, reasons.SERVER_DEAD),
             _row("c", False, reasons.REFUSED_BY_GATEWAY), _row("d", False, reasons.CONTENT_FAILED)]
    cell, = paired.cells(before, after)
    assert (cell.lost, cell.unjudged) == (1, 3)


def test_a_timeout_axis_still_leaves_harness_failures_unjudged():
    before = [_row("a", True), _row("b", True)]
    after = [_row("a", False, reasons.TIMEOUT), _row("b", False, reasons.HARNESS_ERROR)]
    cell, = paired.cells(before, after, paired.UNJUDGED_ON_A_TIMEOUT_AXIS)
    assert (cell.lost, cell.unjudged) == (1, 1)


def test_reverify_pairing_leaves_a_timeout_out_of_lost():
    from harness import reverify
    before = [_row("a", True), _row("b", True)]
    after = [_row("a", False, reasons.TIMEOUT), _row("b", False, reasons.CONTENT_FAILED)]
    cell, lost = reverify._paired(before, after)
    assert (cell.lost, cell.unjudged, [r["case_id"] for r in lost]) == (1, 1, ["b"])


def test_an_mcp_run_lh_timeout_with_no_verb_still_raises_the_tool_error(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    from harness import mcp_server
    monkeypatch.setattr(mcp_server.subprocess, "run", expired)
    with pytest.raises(ToolError, match="timed out"):
        mcp_server.run_lh(list(mcp_server.LH))


def test_a_timeout_seen_by_isinstance_or_returned_as_a_failing_result_is_found():
    bad_isinstance = ("try:\n    go()\nexcept (OSError, RuntimeError) as exc:\n"
                      "    if isinstance(exc, TimeoutError):\n        raise CompletionError('slow') from exc\n")
    bad_return = ("try:\n    go()\nexcept subprocess.TimeoutExpired:\n"
                  "    return CodeResult(False, 'timed out')\n")
    bad_parent = ("try:\n    t = ear(p)\nexcept AudioError as exc:\n"
                  "    return SpeechResult(False, str(exc))\n")
    good_parent = ("try:\n    t = ear(p)\nexcept AudioTimeout as exc:\n"
                   "    return SpeechResult(False, str(exc), failure_class=reasons.TIMEOUT)\n"
                   "except AudioError as exc:\n    return SpeechResult(False, str(exc))\n")
    for bad in (bad_isinstance, bad_return, bad_parent):
        assert scanners.unclassed_timeouts(bad, "m.py") != [], bad
    assert scanners.unclassed_timeouts(good_parent, "m.py") == []


# ---- the render instruments (found by the widened scanner) ----

def test_a_page_chrome_never_shoots_in_time_is_timeout_on_the_render_knob(monkeypatch):
    from harness.checks import render
    monkeypatch.setattr(render, "chrome_path", lambda: "/fake/chrome")
    monkeypatch.setattr(render, "CHROME_TIMEOUT_S", 0.2)
    monkeypatch.setattr(render, "_PROFILE_HANGS", set())

    def slow_shoot(argv, out, cwd, timeout=60.0):
        import time
        # Like _shoot, return only once monotonic has passed the deadline; Windows' coarse clock can trail time.sleep. #869.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.05)
        return "still loading"

    monkeypatch.setattr(render, "_shoot", slow_shoot)
    got = render.check_html("<html><body>hi</body></html>")
    assert (got.ok, got.failure_class, got.limit) == (False, reasons.TIMEOUT, "chrome_render_timeout_s>0.2")


def test_a_chrome_that_will_not_reap_after_kill_is_still_a_timeout_row(monkeypatch):
    from harness.checks import render

    class Unreapable:
        pid = 0

        def __init__(self, *a, **k):
            pass

        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            raise render.subprocess.TimeoutExpired("chrome", timeout)

    monkeypatch.setattr(render, "chrome_path", lambda: "/fake/chrome")
    monkeypatch.setattr(render, "CHROME_TIMEOUT_S", 0.2)
    monkeypatch.setattr(render, "_PROFILE_HANGS", set())
    monkeypatch.setattr(render.subprocess, "Popen", Unreapable)
    # On Windows _kill_tree runs taskkill through subprocess.run, which would get the fake too. #855.
    monkeypatch.setattr(render, "_kill_tree", lambda proc: None)
    got = render.check_html("<html><body>hi</body></html>")
    assert (got.ok, got.failure_class, got.limit) == (False, reasons.TIMEOUT, "chrome_render_timeout_s>0.2")


def test_an_svg_the_rasterizer_cannot_finish_in_time_is_timeout_on_the_render_knob(monkeypatch):
    from harness.checks import render
    monkeypatch.setattr(render, "rasterizer_path", lambda: "/fake/rsvg-convert")
    monkeypatch.setattr(render, "_first_available", lambda names: "/fake/rsvg-convert")
    monkeypatch.setattr(render.subprocess, "run", expired)
    got = render.check('<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>')
    assert (got.ok, got.failure_class, got.limit) == (
        False, reasons.TIMEOUT, f"svg_render_timeout_s>{render.SVG_TIMEOUT_S:g}")


def test_the_web_and_svg_lanes_carry_the_render_class_onto_the_row(monkeypatch):
    from harness.checks import base, render
    hit = base.CheckResult(False, "slow", failure_class=reasons.TIMEOUT, limit="chrome_render_timeout_s>60")
    monkeypatch.setattr(render, "check_html", lambda html: hit)
    monkeypatch.setattr(render, "check", lambda svg: hit)
    web = score(Case(id="w", modality="web", prompt=""), "<!doctype html><html><head><title>t</title></head>"
                "<body><h1>hi</h1></body></html>")
    svg = score(Case(id="s", modality="svg", prompt=""), '<svg xmlns="http://www.w3.org/2000/svg">'
                '<title>t</title><circle r="5"/></svg>')
    assert (web.failure_class, web.limit) == (reasons.TIMEOUT, "chrome_render_timeout_s>60")
    assert (svg.failure_class, svg.limit) == (reasons.TIMEOUT, "chrome_render_timeout_s>60")
