"""The agent lane: cases, sandbox confinement, the tool loop, the Opus baseline. #474."""
import ast
import json
import os
import shutil
import sys
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from evals import agent_pad, run, sandbox
from evals.core import cases_digest, load_cases, summarize
from evals.runners.agent import AgentRunner
from evals.runners.base import BaseRunner
from evals.runners.claude_agent import ClaudeAgentRunner, parse_steps
from harness import lanes

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases" / "agent"


def agent_cases():
    return load_cases(CASES)


def case(case_id):
    return next(c for c in agent_cases() if c.id == case_id)


def bundle(c):
    return c.source.parent / c.params["repo"]


# --- the cases ----------------------------------------------------------------

def test_there_are_enough_cases_in_every_category():
    ids = [c.id for c in agent_cases()]
    assert len(ids) >= 12
    for prefix in ("agent-read-", "agent-edit-", "agent-refactor-", "agent-fix-",
                   "agent-long16k-", "agent-long32k-"):
        assert any(i.startswith(prefix) for i in ids), prefix


def test_every_case_pins_its_tools_and_a_grade():
    for c in agent_cases():
        assert c.modality == "agent"
        assert set(c.params["tools"]) <= set(sandbox.TOOLS)
        assert c.assertions.get("answer") or c.assertions.get("hidden")
        if c.id.startswith("agent-read-"):
            assert "write_file" not in c.params["tools"], c.id


def test_an_edit_case_without_hidden_tests_would_be_refused(tmp_path):
    (tmp_path / "b" / "repo").mkdir(parents=True)
    (tmp_path / "x.yaml").write_text(
        "id: x\nmodality: agent\nprompt: p\nparams: {repo: b, tools: [read_file]}\n"
        "assert: {hidden: true}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hidden"):
        load_cases(tmp_path)
    (tmp_path / "x.yaml").write_text(
        "id: x\nmodality: agent\nprompt: p\nparams: {repo: b, tools: [shell]}\n"
        "assert: {answer: [a]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tools"):
        load_cases(tmp_path)


def test_the_repo_content_is_part_of_the_exam(tmp_path):
    """Editing a case repo must change the cases digest, or two runs on
    different repos would read as the same exam."""
    shutil.copytree(CASES / "repos" / "fix-median", tmp_path / "repos" / "fix-median")
    shutil.copy(CASES / "fix-median.yaml", tmp_path / "fix-median.yaml")
    before = cases_digest(load_cases(tmp_path))
    f = tmp_path / "repos" / "fix-median" / "repo" / "stats.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert cases_digest(load_cases(tmp_path)) != before


@pytest.mark.parametrize("c", [c for c in load_cases(CASES) if c.assertions.get("hidden")],
                         ids=lambda c: c.id)
def test_each_hidden_test_fails_untouched_and_passes_with_the_reference_fix(c):
    """RED-PROOF per case: the hidden test is not vacuous, and it is satisfiable."""
    box = sandbox.Sandbox.create(bundle(c) / "repo")
    try:
        assert not sandbox.grade(box, bundle(c) / "hidden", None, "")["passed"]
        for f in (bundle(c) / "solution").rglob("*.py"):
            box.write_file(f.relative_to(bundle(c) / "solution").as_posix(),
                           f.read_text(encoding="utf-8"))
        got = sandbox.grade(box, bundle(c) / "hidden", None, "")
        assert got["passed"], got
        assert got["hidden_ran"] >= 1
    finally:
        box.cleanup()


@pytest.mark.parametrize("cid", ["agent-fix-median", "agent-fix-paginate",
                                 "agent-fix-duration"])
def test_a_bug_case_starts_with_a_failing_visible_test(cid):
    box = sandbox.Sandbox.create(bundle(case(cid)) / "repo")
    try:
        assert box.run_tests().startswith("exit code 1")
    finally:
        box.cleanup()


@pytest.mark.parametrize("cid,right,wrong", [
    ("agent-read-service-port", "It listens on 8443.", "It listens on 8080."),
    ("agent-read-find-function", "inventory/sku.py", "inventory/stock.py"),
    ("agent-read-count-routes", "There are 5 active routes.", "There are 6 routes."),
])
def test_an_answer_case_tells_right_from_wrong(cid, right, wrong):
    c = case(cid)
    box = sandbox.Sandbox.create(bundle(c) / "repo")
    try:
        assert sandbox.grade(box, None, c.assertions["answer"], right)["passed"]
        assert not sandbox.grade(box, None, c.assertions["answer"], wrong)["passed"]
    finally:
        box.cleanup()


def test_padding_is_deterministic_and_about_the_size_asked():
    a = agent_pad.padding("agent-long32k-x", 32000)
    assert a == agent_pad.padding("agent-long32k-x", 32000)
    assert a != agent_pad.padding("agent-long32k-y", 32000)
    chars = sum(len(t) for t in a.values())
    assert 32000 * 4 <= chars < 32000 * 4 * 1.1
    for text in a.values():
        compile(text, "pad", "exec")


# --- the sandbox ---------------------------------------------------------------

@pytest.fixture
def box(tmp_path):
    src = tmp_path / "src"
    (src / "tests").mkdir(parents=True)
    (src / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (src / "tests" / "test_mod.py").write_text(
        "import unittest\nimport mod\n\nclass T(unittest.TestCase):\n"
        "    def test_x(self):\n        self.assertEqual(mod.X, 1)\n", encoding="utf-8")
    b = sandbox.Sandbox.create(src)
    yield b
    b.cleanup()


ESCAPES = ["../outside.txt", "a/../../outside.txt", "/etc/passwd", "~/x",
           "C:\\Windows\\x", "\\\\server\\share\\x", "mod.py\x00.txt", "..", "a\\..\\..\\x"]


@pytest.mark.parametrize("path", ESCAPES)
def test_a_path_escape_is_refused_for_every_file_tool(box, path):
    for name, args in (("read_file", {"path": path}),
                       ("write_file", {"path": path, "content": "x"}),
                       ("list_dir", {"path": path})):
        call, result = box.call(name, json.dumps(args))
        assert not call.ok and result.startswith("error:"), (name, path)
    assert not (box.root.parent / "outside.txt").exists()


def _symlink(target, link):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")


def test_a_symlink_out_of_the_repo_is_never_followed(box, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cret", encoding="utf-8")
    _symlink(secret, box.root / "link.txt")
    _symlink(tmp_path, box.root / "dirlink")
    assert box.call("read_file", '{"path": "link.txt"}')[1].startswith("error:")
    assert box.call("write_file", '{"path": "link.txt", "content": "x"}')[1].startswith("error:")
    assert box.call("write_file", '{"path": "dirlink/new.txt", "content": "x"}')[1].startswith("error:")
    assert box.call("list_dir", '{"path": "dirlink"}')[1].startswith("error:")
    assert secret.read_text(encoding="utf-8") == "s3cret"
    assert not (tmp_path / "new.txt").exists()


def test_a_case_repo_with_a_symlink_is_refused(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _symlink(tmp_path, src / "up")
    with pytest.raises(ValueError, match="symlink"):
        sandbox.Sandbox.create(src)


@pytest.mark.parametrize("path", ["tests/test_mod.py; rm -rf /", "tests/test_mod.py && ls",
                                  "$(id)", "`id`", "tests/test_mod.py | cat",
                                  "-c import os", "../tests/test_mod.py", "/bin/sh"])
def test_run_tests_refuses_shell_metacharacters(box, path):
    call, result = box.call("run_tests", json.dumps({"path": path}))
    assert not call.ok and "error" in result


def test_only_allowlisted_commands_build_an_argv(box):
    with pytest.raises(sandbox.Refused):
        box.argv("sh", ["-c", "id"])
    argv = box.argv("unittest", ["discover"])
    assert argv[0] == sys.executable and "-I" in argv


def test_no_shell_anywhere_in_the_agent_lane():
    for name in ("evals/sandbox.py", "evals/runners/agent.py",
                 "evals/runners/claude_agent.py", "evals/agent_mcp.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                assert isinstance(node.value, ast.Constant) and node.value.value is False, name
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("system", "popen"), (name, node.attr)


def test_model_written_code_cannot_escape_when_the_tests_run(box, tmp_path):
    """The tests the model writes run under the audit hook."""
    outside = tmp_path / "escaped.txt"
    box.write_file("tests/test_escape.py", textwrap.dedent(f'''\
        import ctypes, os, shutil, socket, subprocess, unittest
        OUT = {str(outside)!r}

        class Escape(unittest.TestCase):
            def test_write(self):
                with self.assertRaises(PermissionError):
                    open(OUT, "w")
            def test_os_open(self):
                with self.assertRaises(PermissionError):
                    os.open(OUT, os.O_WRONLY | os.O_CREAT)
            def test_rename_out(self):
                open("inside.txt", "w").close()
                with self.assertRaises(PermissionError):
                    os.rename("inside.txt", OUT)
            def test_symlink(self):
                with self.assertRaises(PermissionError):
                    os.symlink(OUT, "planted")
            def test_subprocess(self):
                with self.assertRaises(PermissionError):
                    subprocess.run(["echo", "hi"])
            def test_system(self):
                with self.assertRaises(PermissionError):
                    os.system("echo hi")
            def test_socket(self):
                with self.assertRaises(PermissionError):
                    socket.create_connection(("127.0.0.1", 9))
            def test_ctypes(self):
                with self.assertRaises(PermissionError):
                    ctypes.CDLL(None)
            def test_rmtree_out(self):
                with self.assertRaises(PermissionError):
                    shutil.rmtree({str(tmp_path)!r})
            def test_inside_is_fine(self):
                with open("ok.txt", "w") as f:
                    f.write("fine")
        '''))
    result = box.run_tests("tests/test_escape.py")
    assert result.startswith("exit code 0"), result
    assert "Ran 10 tests" in result
    assert not outside.exists() and tmp_path.exists()
    assert (box.root / "ok.txt").read_text(encoding="utf-8") == "fine"


def test_a_test_run_is_time_capped(tmp_path):
    src = tmp_path / "src"
    (src / "tests").mkdir(parents=True)
    (src / "tests" / "test_slow.py").write_text(
        "import time, unittest\nclass T(unittest.TestCase):\n"
        "    def test_x(self):\n        time.sleep(30)\n", encoding="utf-8")
    b = sandbox.Sandbox.create(src, test_timeout=1.0)
    try:
        started = time.perf_counter()
        assert "timed out" in b.run_tests()
        assert time.perf_counter() - started < 15
    finally:
        b.cleanup()


def test_a_write_is_size_capped(box):
    call, result = box.call("write_file", json.dumps(
        {"path": "big.txt", "content": "x" * (sandbox.WRITE_CAP + 1)}))
    assert not call.ok and not (box.root / "big.txt").exists()


def test_call_validity_is_recorded(box):
    assert box.call("read_file", '{"path": "mod.py"}')[0].valid
    unknown = box.call("delete_file", '{"path": "mod.py"}')[0]
    assert not unknown.real and not unknown.valid
    bad_json = box.call("read_file", '{"path": ')[0]
    assert bad_json.real and not bad_json.parsed
    bad_schema = box.call("read_file", '{"file": "mod.py"}')[0]
    assert bad_schema.parsed and not bad_schema.schema_ok and not bad_schema.valid
    wrong_type = box.call("write_file", '{"path": "a.txt", "content": 5}')[0]
    assert not wrong_type.schema_ok
    refused = box.call("read_file", '{"path": "/etc/passwd"}')[0]
    assert refused.valid and not refused.ok


def test_an_unpinned_tool_is_not_real(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    b = sandbox.Sandbox.create(src, tools=("read_file",))
    try:
        call, _ = b.call("write_file", '{"path": "a.txt", "content": "x"}')
        assert not call.real and not (b.root / "a.txt").exists()
    finally:
        b.cleanup()


# --- the tool loop against a fake OpenAI server ---------------------------------

class Fake(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, script):
        super().__init__(("127.0.0.1", 0), Handler)
        self.script = list(script)
        self.seen = []

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append(payload)
        turn = self.server.script.pop(0) if self.server.script else {"content": "done"}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def emit(delta, **extra):
            chunk = {"choices": [{"index": 0, "delta": delta, **extra}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        emit({"role": "assistant"})
        time.sleep(0.05)
        if turn.get("content"):
            emit({"content": turn["content"]})
        for i, (name, args) in enumerate(turn.get("calls", [])):
            raw = args if isinstance(args, str) else json.dumps(args)
            emit({"tool_calls": [{"index": i, "id": f"c{i}", "type": "function",
                                  "function": {"name": name, "arguments": ""}}]})
            half = len(raw) // 2
            emit({"tool_calls": [{"index": i, "function": {"arguments": raw[:half]}}]})
            emit({"tool_calls": [{"index": i, "function": {"arguments": raw[half:]}}]})
        emit({}, finish_reason="tool_calls" if turn.get("calls") else "stop")
        usage = {"usage": {"prompt_tokens": 100, "completion_tokens": 10}, "choices": []}
        self.wfile.write(f"data: {json.dumps(usage)}\n\ndata: [DONE]\n\n".encode())


@pytest.fixture
def serve():
    servers = []

    def start(script):
        s = Fake(script)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
        return s
    yield start
    for s in servers:
        s.shutdown()


def _fix(c, name):
    return (bundle(c) / "solution" / name).read_text(encoding="utf-8")


def test_a_model_that_uses_the_tools_completes_the_task(serve):
    c = case("agent-fix-median")
    s = serve([{"calls": [("list_dir", {})]},
               {"calls": [("read_file", {"path": "stats.py"})]},
               {"calls": [("write_file", {"path": "stats.py", "content": _fix(c, "stats.py")}),
                          ("run_tests", {})]},
               {"content": "Fixed median for even counts."}])
    r = AgentRunner(s.url, "fake").run(c)
    assert r.passed, r.detail
    m = r.metrics
    assert m["agent_steps"] == 4 and m["agent_tool_calls"] == 4
    assert m["agent_valid_call_rate"] == 1.0
    assert m["agent_ttft_sum_s"] > 0.15 and r.ttft_s is not None
    assert m["prompt_tokens"] == 400
    assert s.seen[0]["stream"] is True and s.seen[0]["tools"]
    assert {t["function"]["name"] for t in s.seen[0]["tools"]} == set(c.params["tools"])
    tool_msgs = [m for m in s.seen[-1]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 4 and "exit code 0" in tool_msgs[-1]["content"]


def test_a_model_that_never_calls_a_tool_fails_the_step_not_the_harness(serve):
    s = serve([{"content": "The port is 8443."}])
    r = AgentRunner(s.url, "fake").run(case("agent-read-service-port"))
    assert not r.passed and "tool" in r.detail
    record = json.loads(r.output)
    assert record["steps"][0]["failed"] == "no tool call"
    assert r.metrics["agent_no_tool_steps"] == 1


def test_invalid_calls_are_counted_and_the_loop_goes_on(serve):
    c = case("agent-read-service-port")
    s = serve([{"calls": [("shell", {"cmd": "cat /etc/passwd"}),
                          ("read_file", '{"path": '),
                          ("read_file", {"file": "x"})]},
               {"calls": [("read_file", {"path": "config/production.ini"})]},
               {"content": "<tool_call>{\"name\": \"read_file\"}</tool_call>"},
               {"content": "Production listens on 8443."}])
    r = AgentRunner(s.url, "fake").run(c)
    assert r.passed, r.detail
    assert r.metrics["agent_tool_calls"] == 5 and r.metrics["agent_valid_calls"] == 1
    summary = summarize([r])["fake"]["metrics"]
    assert summary["agent_valid_call_rate"] == 0.2


def test_the_step_cap_stops_a_model_that_never_finishes(serve):
    c = case("agent-read-service-port")
    s = serve([{"calls": [("list_dir", {})]}] * 50)
    r = AgentRunner(s.url, "fake").run(c)
    assert not r.passed
    assert r.metrics["agent_steps"] == c.params["max_steps"]
    assert json.loads(r.output)["stopped"] == "step cap"


def test_a_long_context_case_puts_the_padded_repo_in_the_first_message(serve):
    c = case("agent-long16k-fix-median")
    s = serve([{"content": "no"}])
    AgentRunner(s.url, "fake").run(c)
    first = s.seen[0]["messages"][1]["content"]
    assert len(first) >= 16000 * agent_pad.CHARS_PER_TOKEN
    assert "=== stats.py ===" in first and "=== vendor/" in first


def test_the_sandbox_is_gone_after_a_case(serve, monkeypatch):
    made = []
    real = sandbox.Sandbox.create

    def spy(*a, **kw):
        b = real(*a, **kw)
        made.append(b.root)
        return b
    monkeypatch.setattr(sandbox.Sandbox, "create", spy)
    s = serve([{"content": "x"}])
    AgentRunner(s.url, "fake").run(case("agent-fix-median"))
    assert made and not made[0].exists()


def test_an_unreachable_server_is_a_runner_error_row():
    r = AgentRunner("http://127.0.0.1:9", "fake").run(case("agent-fix-median"))
    assert not r.passed and r.failure_class


# --- evals.run wiring ------------------------------------------------------------

def test_evals_run_builds_the_loop_for_the_agent_modality():
    r = run.build_runner("q3-coder,temperature=0", "http://gw", None, modality="agent")
    assert isinstance(r, AgentRunner) and r.gateway == "http://gw" and r.model == "q3-coder"
    assert r.sampling == {"temperature": 0.0}
    r = run.build_runner("claude-code:claude-opus-5-5", "http://gw", None, modality="agent")
    assert isinstance(r, ClaudeAgentRunner) and r.candidate == "claude-code:claude-opus-5-5"
    with pytest.raises(SystemExit):
        run.build_runner("mflux:z-image-turbo", "http://gw", None, modality="agent")


def test_all_leaves_the_agent_lane_out_and_agent_asks_for_it():
    every = load_cases(ROOT / "evals" / "cases")
    assert not [c for c in run.select_cases(every, "all") if c.modality == "agent"]
    assert all(c.modality == "agent" for c in run.select_cases(every, "agent"))
    assert run.cases_for("q3-coder", run.select_cases(every, "agent"))


def test_agent_is_a_wanted_text_served_lane():
    assert "agent" in lanes.WANTED and "agent" in lanes.TEXT_SERVED
    assert lanes.serves("code", "agent")


# --- the Opus baseline: claude -p on the same sandbox over MCP ---------------------

FAKE_CLAUDE = textwrap.dedent(r'''
    import json, subprocess, sys, time
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    cfg = json.load(open(argv[argv.index("--mcp-config") + 1], encoding="utf-8"))
    assert argv[argv.index("--tools") + 1] == ""
    allowed = argv[argv.index("--allowedTools") + 1]
    goal = sys.stdin.read()
    server = cfg["mcpServers"]["sandbox"]
    p = subprocess.Popen([server["command"], *server["args"]], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True, encoding="utf-8")
    def rpc(i, method, params=None):
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method,
                                  "params": params or {}}) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())
    def out(obj):
        print(json.dumps(obj), flush=True)
    rpc(1, "initialize", {"protocolVersion": "2025-06-18"})
    tools = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
    assert all(f"mcp__sandbox__{t}" in allowed for t in tools)
    fix = json.load(open(sys.argv[0] + ".json", encoding="utf-8"))
    plan = [("write_file", {"path": "stats.py", "content": fix}), ("run_tests", {}),
            ("read_file", {"path": "../../etc/passwd"})]
    for n, (name, args) in enumerate(plan):
        out({"type": "stream_event", "event": {"type": "message_start",
             "message": {"usage": {"input_tokens": 50}}}})
        time.sleep(0.05)
        out({"type": "stream_event", "event": {"type": "content_block_start",
             "content_block": {"type": "tool_use", "name": "mcp__sandbox__" + name}}})
        out({"type": "stream_event", "event": {"type": "message_delta",
             "usage": {"output_tokens": 7}}})
        out({"type": "stream_event", "event": {"type": "message_stop"}})
        rpc(10 + n, "tools/call", {"name": name, "arguments": args})
        out({"type": "user", "message": {"content": [{"type": "tool_result"}]}})
    out({"type": "stream_event", "event": {"type": "message_start", "message": {}}})
    out({"type": "stream_event", "event": {"type": "content_block_delta",
         "delta": {"type": "text_delta", "text": "Fixed."}}})
    out({"type": "stream_event", "event": {"type": "message_stop"}})
    p.stdin.close()
    p.wait()
    out({"type": "result", "is_error": False, "result": "Fixed the median.",
         "usage": {"output_tokens": 30}})
''')


def test_the_opus_baseline_works_the_same_sandbox_over_mcp(tmp_path):
    c = case("agent-fix-median")
    fake = tmp_path / "claude_fake.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    (tmp_path / "claude_fake.py.json").write_text(json.dumps(_fix(c, "stats.py")),
                                                 encoding="utf-8")
    r = ClaudeAgentRunner("claude-opus-5-5", binary=(sys.executable, str(fake))).run(c)
    assert r.passed, (r.detail, r.output)
    m = r.metrics
    assert m["agent_steps"] == 4 and m["agent_tool_calls"] == 3
    assert m["agent_valid_calls"] == 3 and m["agent_valid_call_rate"] == 1.0
    steps = json.loads(r.output)["steps"]
    assert steps[2]["calls"][0]["ok"] is False
    assert all(s["ttft_s"] is not None for s in steps)


def test_a_tool_use_that_never_reached_the_sandbox_is_invalid():
    lines = [(0.1, json.dumps({"type": "stream_event", "event": {"type": "message_start",
                                                                 "message": {}}})),
             (0.2, json.dumps({"type": "stream_event", "event": {
                 "type": "content_block_start",
                 "content_block": {"type": "tool_use", "name": "mcp__sandbox__read_file"}}}))]
    steps = parse_steps(lines, [])
    assert steps[0]["calls"][0]["valid"] is False and steps[0]["ttft_s"] == 0.2


def test_a_runner_returns_text_so_the_run_writes_the_transcript():
    assert issubclass(AgentRunner, BaseRunner) and issubclass(ClaudeAgentRunner, BaseRunner)
