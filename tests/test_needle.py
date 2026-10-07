"""The needle: runner kind (Cactus-Compute/needle3) in the decide and agent lanes. #312."""
import json
import os
import sys
from pathlib import Path

import pytest

from evals import run
from evals.core import Case, load_cases
from harness import needle

ROOT = Path(__file__).resolve().parents[1]

FAKE = r'''
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
argv = sys.argv[1:]
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None
log = os.environ.get("FAKE_NEEDLE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(argv) + "\n")
tools = json.load(open(opt("--tools"), encoding="utf-8"))
def answer(text):
    if "OVERFLOW" in text and "--fail-input-overflow" in argv:
        return {"type": "call", "success": False,
                "error": "input exceeds the context window (9000 tokens, 7634 available)",
                "function_calls": [], "suppressed_calls": [], "confidence": 0.0}
    fn = tools[0]["function"]
    args = {}
    for name, p in fn["parameters"]["properties"].items():
        args[name] = True if p.get("type") == "boolean" else p["enum"][-1]
    return {"type": "call", "success": True, "error": None,
            "function_calls": [{"name": fn["name"], "arguments": args}],
            "suppressed_calls": [], "reasoning": "fake", "confidence": 0.8,
            "peak_ram_mb": 12.5}
if "--serve" not in argv:
    print(json.dumps(answer(opt("--prompt"))))
    sys.exit(0)
from http.server import BaseHTTPRequestHandler, HTTPServer
turns = []
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        if self.path == "/reset":
            turns.clear()
            out = {}
        else:
            turns.append(body["input"])
            if log:
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"input": body["input"]}) + "\n")
            if len(turns) == 1:
                out = {"type": "call", "success": True, "error": None,
                       "function_calls": [{"name": "list_dir", "arguments": {"path": "."}},
                                          {"name": "nope", "arguments": {}}],
                       "suppressed_calls": [], "reasoning": "look", "confidence": 0.5}
                if os.environ.get("FAKE_NEEDLE_WITHHOLD"):
                    out["suppressed_calls"], out["function_calls"] = out["function_calls"], []
            else:
                out = {"type": "respond", "success": True, "error": None,
                       "function_calls": [], "suppressed_calls": [],
                       "reasoning": "done: 5 routes", "confidence": 0.6}
        data = json.dumps(out).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
srv = HTTPServer(("127.0.0.1", int(opt("--port") or 8080)), H)
shown = 0 if os.environ.get("FAKE_NEEDLE_PRINT_ZERO") else srv.server_address[1]
print(f"needle serving on http://127.0.0.1:{shown}  (POST /complete)", flush=True)
srv.serve_forever()
'''

SCHEMA = {
    "route": {"type": "enum", "choices": ["billing", "tech", "other"],
              "description": "Which team handles it", "choice_descriptions": {"tech": "a fault"}},
    "urgent": {"type": "boolean", "description": "Is it urgent"},
}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    path = tmp_path / "fake_needle.py"
    path.write_text(FAKE, encoding="utf-8")
    log = tmp_path / "argv.log"
    monkeypatch.setenv("FAKE_NEEDLE_LOG", str(log))
    return [sys.executable, str(path)], log


def _logged(log):
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]


# --- the spec ----------------------------------------------------------------

def test_a_needle_spec_names_its_layers_and_refuses_what_it_cannot_run():
    assert needle.parse("needle:needle3").name == "needle/needle3"
    assert needle.parse("needle:needle3,layers=8").name == "needle/needle3@layers=8"
    assert needle.parse("needle:needle3,layers=8").layers == 8
    for bad in ("needle:", "needle:other-model", "needle:needle3,layers=1",
                "needle:needle3,layers=21", "needle:needle3,temperature=1"):
        with pytest.raises(ValueError):
            needle.parse(bad)


def test_needle_is_its_own_runner_kind_for_the_decide_and_agent_lanes():
    assert run.kind_of("needle:needle3") == "needle"
    cases = [Case(id=m, modality=m, prompt="p") for m in ("decide", "agent", "code", "image")]
    assert [c.id for c in run.cases_for("needle:needle3", cases)] == ["decide", "agent"]


def test_the_argv_carries_depth_threads_and_refuses_a_silent_trim(tmp_path):
    spec = needle.parse("needle:needle3,layers=6,threads=2")
    argv = needle.argv(spec, ["needle"], "w.cact", tmp_path / "t.json", prompt="hi")
    assert argv[:3] == ["needle", "--model", "w.cact"]
    assert argv[argv.index("--depth") + 1] == "6"
    assert argv[argv.index("--threads") + 1] == "2"
    assert "--fail-input-overflow" in argv and "--forced" in argv
    assert argv[argv.index("--prompt") + 1] == "hi"


# --- decide ------------------------------------------------------------------

def test_each_field_is_one_tool_whose_argument_is_constrained_to_its_choices():
    tools = needle.field_tools("route", SCHEMA["route"])
    params = tools[0]["function"]["parameters"]["properties"]["value"]
    assert params == {"type": "string", "enum": ["billing", "tech", "other"],
                      "description": "Which team handles it"}
    assert "tech: a fault" in tools[0]["function"]["description"]
    flag = needle.field_tools("urgent", SCHEMA["urgent"])[0]["function"]["parameters"]
    assert flag["properties"]["value"]["type"] == "boolean"


def test_the_question_comes_after_the_material():
    text = needle.field_input("Route this ticket.", "the printer is on fire", SCHEMA["route"])
    assert text.index("the printer is on fire") < text.index("Which team handles it")


def test_a_whole_call_confidence_is_not_a_per_option_distribution():
    got = needle.field_answer({"function_calls": [{"name": "answer", "arguments": {"value": "tech"}}],
                               "confidence": 0.7}, SCHEMA["route"])
    assert got["answer"] == "tech"
    assert got["probs"] == pytest.approx({"tech": 0.7, "billing": 0.15, "other": 0.15})
    flag = needle.field_answer({"function_calls": [{"name": "answer", "arguments": {"value": False}}],
                                "confidence": 0.9}, SCHEMA["urgent"])
    assert flag["answer"] == "false" and flag["probs"] == pytest.approx({"false": 0.9, "true": 0.1})


def test_no_confidence_means_no_probabilities_and_a_withheld_call_still_answers():
    got = needle.field_answer({"function_calls": [], "confidence": None,
                               "suppressed_calls": [{"name": "answer", "arguments": {"value": "other"}}]},
                              SCHEMA["route"])
    assert got == {"answer": "other", "probs": None, "suppressed": True, "error": None}


def test_an_overflow_is_recorded_as_no_answer_with_the_runtimes_reason():
    got = needle.field_answer({"success": False, "error": "input exceeds the context window "
                               "(9000 tokens, 7634 available)", "function_calls": []}, SCHEMA["route"])
    assert got["answer"] is None and "context window" in got["error"]


def test_a_decide_case_runs_through_the_fake_binary_and_is_scored(fake, tmp_path):
    from evals.runners.needle import NeedleDecideRunner
    command, log = fake
    r = NeedleDecideRunner("needle:needle3,layers=4", tmp_path / "out",
                           command=command, weights="w.cact").run(
        Case(id="d", modality="decide", prompt="Route it.", context="ctx ü",
             params={"schema": SCHEMA}, assertions={"answers": {"route": "other", "urgent": True}}))
    assert r.passed, r.detail
    assert r.candidate == "needle/needle3@layers=4"
    assert r.metrics["calibrated"] == 1.0
    assert r.metrics["per_option"] == 0.0
    assert r.metrics["decide_brier_sum"] == pytest.approx((0.2 ** 2 + 2 * 0.1 ** 2) + 2 * 0.2 ** 2)
    body = json.loads(Path(r.artifact_path).read_text(encoding="utf-8"))
    assert body["per_option"] is False and body["confidence"] == {"route": 0.8, "urgent": 0.8}
    calls = _logged(log)
    assert len(calls) == 2 and all(c[c.index("--depth") + 1] == "4" for c in calls)
    if sys.platform == "darwin":
        assert r.peak_kb > 0


def test_an_overflowing_case_fails_and_says_why(fake, tmp_path):
    from evals.runners.needle import NeedleDecideRunner
    command, _ = fake
    r = NeedleDecideRunner("needle:needle3", tmp_path / "out", command=command,
                           weights="w.cact").run(
        Case(id="d", modality="decide", prompt="p", context="OVERFLOW",
             params={"schema": SCHEMA}, assertions={"answers": {"route": "other", "urgent": True}}))
    assert not r.passed
    body = json.loads(Path(r.artifact_path).read_text(encoding="utf-8"))
    assert "context window" in body["errors"]["route"]


def test_the_real_decide_cases_strip_the_lettered_block_needle_does_not_read():
    case = load_cases(ROOT / "evals" / "cases" / "decide")[0]
    task = needle.task_of(case.prompt, case.params["schema"])
    assert task and "letter" not in task and task in case.prompt


# --- agent -------------------------------------------------------------------

def test_the_tool_loop_drives_the_fake_server_and_feeds_results_back_as_json(fake, tmp_path):
    from evals.runners.needle import needle_agent_runner
    command, log = fake
    runner = needle_agent_runner("needle:needle3", command=command, weights="w.cact", port=0)
    case = load_cases(ROOT / "evals" / "cases" / "agent")
    case = next(c for c in case if c.id == "agent-read-count-routes")
    try:
        r = runner.run(case)
    finally:
        runner.close()
    transcript = json.loads(r.output)
    assert transcript["stopped"] == "answered"
    assert transcript["final"] == "done: 5 routes"
    assert r.metrics["agent_tool_calls"] == 2 and r.metrics["agent_valid_calls"] == 1
    inputs = [x["input"] for x in _logged(log) if isinstance(x, dict)]
    assert inputs[0].startswith("How many HTTP routes")
    results = json.loads(inputs[1])
    assert [x["name"] for x in results] == ["list_dir", "nope"]
    argv = next(x for x in _logged(log) if isinstance(x, list))
    assert "--serve" in argv and "--system" in argv and "--fail-input-overflow" in argv


def test_an_agent_turn_maps_to_an_openai_message():
    msg = needle.message({"type": "call", "function_calls": [
        {"name": "read_file", "arguments": {"path": "a.py"}}], "reasoning": "r"}, step=3)
    call = msg["tool_calls"][0]
    assert call["function"] == {"name": "read_file", "arguments": '{"path": "a.py"}'}
    assert call["id"] == "call_3_0"
    assert needle.message({"type": "respond", "function_calls": [], "reasoning": "ok"},
                          step=1) == {"role": "assistant", "content": "ok"}


# --- install and version -----------------------------------------------------

def test_the_runtime_version_is_the_engine_version_at_the_pinned_revision(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"engine_version": "3.1.0"}), encoding="utf-8")
    assert needle.installed_version(lambda repo, name, revision: str(cfg)) == \
        f"3.1.0@{needle.REVISION[:7]}"
    assert needle.installed_version(lambda repo, name, revision: None) == ""


def test_machine_versions_records_needle_when_it_is_installed(monkeypatch):
    from harness import machine
    monkeypatch.setattr(needle, "installed_version", lambda *a, **k: "3.1.0@abcdef0")
    machine.versions.cache_clear()
    try:
        assert machine.versions()["needle"] == "3.1.0@abcdef0"
    finally:
        machine.versions.cache_clear()


def test_the_platform_folder_is_the_cards_and_unknown_platforms_are_refused():
    assert needle.platform_binary("darwin", "arm64") == "macos-arm64/needle"
    assert needle.platform_binary("linux", "x86_64") == "linux-x86_64/needle"
    with pytest.raises(ValueError):
        needle.platform_binary("sunos", "sparc")


def test_telemetry_is_off_in_the_child_environment():
    assert needle.child_env({"PATH": "/bin"})["NEEDLE_TELEMETRY"] == "0"


@pytest.mark.skipif(sys.platform != "darwin", reason="the needle binary measured here is macOS arm64")
@pytest.mark.skipif(not (os.environ.get("NEEDLE_BIN") and os.environ.get("NEEDLE_MODEL")),
                    reason="set NEEDLE_BIN and NEEDLE_MODEL to a fetched needle3 to run it")
def test_the_real_binary_answers_one_field(tmp_path):
    command, weights = needle.installed(download=False)
    out = needle.ask_field(needle.parse("needle:needle3"), command, weights, "urgent",
                           SCHEMA["urgent"], "Route it.", "The server room is flooding now.", tmp_path)
    assert out["answer"] in ("true", "false")


def test_the_per_option_marker_is_reported_not_ranked_on():
    from evals.core import METRIC_DIRECTION
    assert METRIC_DIRECTION["per_option"] == "neutral"


def test_a_withheld_call_is_confirmed_and_counted(fake, tmp_path, monkeypatch):
    from evals.runners.needle import needle_agent_runner
    command, _ = fake
    monkeypatch.setenv("FAKE_NEEDLE_WITHHOLD", "1")
    runner = needle_agent_runner("needle:needle3", command=command, weights="w.cact", port=0)
    case = next(c for c in load_cases(ROOT / "evals" / "cases" / "agent")
                if c.id == "agent-read-count-routes")
    try:
        r = runner.run(case)
    finally:
        runner.close()
    assert r.metrics["agent_tool_calls"] == 2 and r.metrics["agent_valid_calls"] == 1
    assert r.metrics["needle_withheld_calls"] == 2
    assert "needle_peak_mb" not in r.metrics


def test_the_server_is_found_when_the_runtime_prints_port_zero(fake, monkeypatch, tmp_path):
    command, _ = fake
    monkeypatch.setenv("FAKE_NEEDLE_PRINT_ZERO", "1")
    tools = tmp_path / "t.json"
    tools.write_text("[]", encoding="utf-8")
    spec = needle.parse("needle:needle3")
    server = needle.Server(lambda port: needle.serve_argv(spec, command, "w.cact", tools,
                                                          tools, port), None)
    try:
        assert not server.base.endswith(":0")
        assert server.post("/reset", {}, 10) == {}
    finally:
        server.close()
