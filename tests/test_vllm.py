"""A `vllm:` text engine behind serving.route, and a sweep that labels and sizes it. #310."""
import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from evals import run as R
from evals.runners.text import CompletionRunner
from harness import cli, gateway, machine, reverify, serving, throughput, vllm


class Fake(ThreadingHTTPServer):
    """An OpenAI-compatible server that streams four tokens and reports usage."""
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.seen = []

    @property
    def port(self):
        return self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "m"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append(payload)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ("a", "b", "c", "d"):
            chunk = {"choices": [{"index": 0, "delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        usage = {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 4}}
        self.wfile.write(f"data: {json.dumps(usage)}\n\ndata: [DONE]\n\n".encode())


@pytest.fixture
def fake(monkeypatch):
    server = Fake()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv(serving.VLLM_PORT_VAR, str(server.port))
    yield server
    server.shutdown()


# ---- serving.route and the engine label -------------------------------------

def test_a_vllm_spec_routes_to_the_vllm_server_even_with_a_gateway(monkeypatch):
    monkeypatch.delenv(serving.VLLM_PORT_VAR, raising=False)
    got = serving.route("vllm:mlx-community/Qwen3-4B,temperature=0",
                        gateway="http://127.0.0.1:4000")
    assert got == serving.Route(serving.VLLM_URL, "mlx-community/Qwen3-4B",
                                {"temperature": 0.0})
    monkeypatch.setenv(serving.VLLM_PORT_VAR, "18310")
    assert serving.route("vllm:m").base == "http://127.0.0.1:18310"


def test_a_vllm_spec_is_a_text_spec_and_an_empty_one_is_refused():
    assert serving.text_spec("vllm:m")
    with pytest.raises(ValueError):
        serving.route("vllm:")


def test_the_engine_names_which_vllm(monkeypatch):
    monkeypatch.delenv(serving.VLLM_ENGINE_VAR, raising=False)
    assert serving.engine_for("vllm:m") == "vllm-mlx"
    monkeypatch.setenv(serving.VLLM_ENGINE_VAR, "vllm-metal")
    assert serving.engine_for("vllm:m") == "vllm-metal"
    monkeypatch.setenv(serving.VLLM_ENGINE_VAR, "vllm-cuda")
    with pytest.raises(ValueError):
        serving.engine_for("vllm:m")


def test_a_gateway_alias_fronting_vllm_is_labelled_vllm(tmp_path, monkeypatch):
    monkeypatch.delenv(serving.VLLM_PORT_VAR, raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""\
        model_list:
          - model_name: fast-4b
            litellm_params:
              model: openai/m
              api_base: {serving.VLLM_URL}/v1
          - model_name: q3-4b
            litellm_params:
              model: openai/m
              api_base: http://127.0.0.1:8081/v1
        """), encoding="utf-8")
    assert serving.engine_for("fast-4b", environ={}, config=cfg) == "vllm-mlx"
    assert serving.engine_for("q3-4b", environ={}, config=cfg) == serving.DEFAULT


def test_the_generated_gateway_config_fronts_a_vllm_adoption(tmp_path, monkeypatch):
    monkeypatch.delenv(serving.VLLM_PORT_VAR, raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model_list: []\n", encoding="utf-8")
    got = gateway.served(cfg, defaults={"code": "vllm:mlx-community/Qwen3-4B"})
    alias = {e["model_name"]: e for e in got["model_list"]}["sohot-code"]
    assert alias["litellm_params"]["api_base"] == f"{serving.VLLM_URL}/v1"
    assert alias["litellm_params"]["model"] == "openai/mlx-community/Qwen3-4B"


# ---- evals.run --------------------------------------------------------------

def test_a_vllm_candidate_is_a_text_candidate_with_its_engine_on_the_receipt(monkeypatch):
    monkeypatch.delenv(serving.VLLM_ENGINE_VAR, raising=False)
    assert R.kind_of("vllm:m") == R.VLLM_KIND
    assert R.engines(["vllm:m", "q3-4b"])["vllm:m"] == "vllm-mlx"
    assert R.greedy(["vllm:m"]) == ["vllm:m,temperature=0"]
    assert R.modality_of("vllm:m") is None


def test_a_vllm_candidate_is_answered_by_the_vllm_server(monkeypatch):
    monkeypatch.setenv(serving.VLLM_PORT_VAR, "18310")
    runner = R.build_runner("vllm:m", "http://127.0.0.1:4000", None, modality="code")
    assert isinstance(runner, CompletionRunner)
    assert runner.gateway == "http://127.0.0.1:18310" and runner.model == "m"


def test_a_vllm_spec_is_stale_when_vllm_changes():
    assert "vllm-mlx" in reverify.runtimes_for("code", "vllm:m")
    assert "mlx-lm" not in reverify.runtimes_for("code", "vllm:m")


# ---- versions (#415) --------------------------------------------------------

def test_the_vllm_venvs_report_their_versions(tmp_path, monkeypatch):
    site = tmp_path / "vllm-mlx" / "lib" / "python3.12" / "site-packages"
    (site / "vllm_mlx-0.5.0.dist-info").mkdir(parents=True)
    monkeypatch.setenv(vllm.VENV_VAR, str(tmp_path / "vllm-mlx"))
    assert {"vllm-mlx", "vllm-metal", "vllm"} <= set(machine.WATCHED)
    assert tmp_path / "vllm-mlx" in machine._other_venvs()
    assert machine._site_versions(tmp_path / "vllm-mlx")["vllm-mlx"] == "0.5.0"


# ---- the launcher -----------------------------------------------------------

def test_each_engine_is_launched_with_batching_and_a_memory_cap(tmp_path):
    mlx = vllm.argv("vllm-mlx", "m", 18310, venv=tmp_path)
    assert mlx[:3] == [str(tmp_path / "bin" / "vllm-mlx"), "serve", "m"]
    assert "--continuous-batching" in mlx and mlx[mlx.index("--port") + 1] == "18310"
    metal = vllm.argv("vllm-metal", "m", 18311, venv=tmp_path)
    assert metal[:3] == [str(tmp_path / "bin" / "vllm"), "serve", "m"]
    assert float(metal[metal.index("--gpu-memory-utilization") + 1]) <= 0.3
    assert int(metal[metal.index("--max-model-len") + 1]) <= 32768
    with pytest.raises(ValueError):
        vllm.argv("vllm-cuda", "m", 1)


FAKE_CHILD = textwrap.dedent("""\
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port = int(sys.argv[1])
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            body = json.dumps({"data": [{"id": "m"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    print("serving \\u2713 on", port, flush=True)
    HTTPServer(("127.0.0.1", port), H).serve_forever()
    """)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _utf8_env():
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def test_served_starts_the_child_waits_for_it_and_stops_it(tmp_path):
    child = tmp_path / "child.py"
    child.write_text(FAKE_CHILD, encoding="utf-8")
    port = _free_port()
    log = tmp_path / "server.log"
    with vllm.served([sys.executable, str(child), str(port)], port, log=log,
                     env=_utf8_env(), timeout=20) as srv:
        assert srv.base == f"http://127.0.0.1:{port}"
        assert srv.proc.poll() is None
    assert srv.proc.poll() is not None
    assert "serving ✓" in log.read_text(encoding="utf-8")


def test_a_child_that_dies_before_it_serves_is_an_error_with_its_log(tmp_path):
    child = tmp_path / "child.py"
    child.write_text("import sys\nprint('no metal ✗', flush=True)\nsys.exit(3)\n",
                     encoding="utf-8")
    with pytest.raises(RuntimeError, match="no metal"):
        with vllm.served([sys.executable, str(child)], _free_port(),
                         log=tmp_path / "server.log", env=_utf8_env(), timeout=20):
            pass


# ---- the sweep --------------------------------------------------------------

def test_the_sweep_reports_tokens_per_second_and_peak_memory():
    import itertools
    now = [0.0]

    def post(payload):
        now[0] += 0.5
        return {"usage": {"completion_tokens": 50}}
    samples = itertools.chain([1_000, 5_000], itertools.repeat(3_000))
    got = throughput.sweep("m", ["t"] * 4, levels=(1,), post=post,
                           clock=lambda: now[0], footprint=lambda: next(samples),
                           sample_s=60)
    assert got[0]["wall_s"] == 2.0 and got[0]["tokens_per_s"] == 100.0
    assert got[0]["peak_bytes"] == 5_000


def test_the_peak_is_per_level():
    samples = iter([1_000, 5_000, 3_000, 3_000])
    got = throughput.sweep("m", ["t"], levels=(1, 2), post=lambda p: {"usage": {}},
                           footprint=lambda: next(samples), sample_s=60)
    assert [r["peak_bytes"] for r in got] == [5_000, 3_000]


def test_without_a_server_to_watch_there_is_no_peak():
    got = throughput.sweep("m", ["t"], levels=(1,), post=lambda p: {"usage": {}})
    assert got[0]["peak_bytes"] is None


def test_footprint_of_a_process_tree_counts_its_children():
    if sys.platform != "darwin":
        assert throughput.footprint_tree(os.getpid()) is None
        return
    child = subprocess.Popen([sys.executable, "-c",
                              "b = bytearray(64 * 2**20); import time; time.sleep(30)"])
    try:
        import time
        time.sleep(1.0)
        alone = throughput.footprint_tree(child.pid)
        tree = throughput.footprint_tree(os.getpid())
        assert alone > 60 * 2**20
        assert tree >= alone
    finally:
        child.kill()
        child.wait()


def test_soh_throughput_routes_a_vllm_spec_and_labels_the_engine(fake, tmp_path, capsys,
                                                                 monkeypatch):
    monkeypatch.delenv(serving.VLLM_ENGINE_VAR, raising=False)
    texts = tmp_path / "t.jsonl"
    texts.write_text('{"text": "a"}\n{"text": "b"}\n', encoding="utf-8")
    assert cli.main(["throughput", "--model", "vllm:m", "--texts", str(texts),
                     "--levels", "1,2", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["engines"] == {"vllm:m": "vllm-mlx"}
    assert [r["concurrency"] for r in out["levels"]] == [1, 2]
    assert out["levels"][0]["completion_tokens"] == 8
    assert out["levels"][0]["tokens_per_s"] > 0
    assert {p["model"] for p in fake.seen} == {"m"}


def test_soh_throughput_serves_the_engine_for_the_sweep_and_stops_it(fake, tmp_path,
                                                                    capsys, monkeypatch):
    texts = tmp_path / "t.jsonl"
    texts.write_text('{"text": "a"}\n', encoding="utf-8")
    calls = []

    class Srv:
        base = f"http://127.0.0.1:{fake.port}"

        class proc:
            pid = os.getpid()

    import contextlib

    @contextlib.contextmanager
    def served(argv, port, **kw):
        calls.append(("up", argv, port))
        yield Srv
        calls.append(("down",))
    monkeypatch.setattr(vllm, "served", served)
    assert cli.main(["throughput", "--model", "vllm:m", "--texts", str(texts),
                     "--levels", "1", "--serve", "vllm-metal", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert calls[0][0] == "up" and calls[-1] == ("down",)
    assert calls[0][1][1:3] == ["serve", "m"] and calls[0][2] == fake.port
    assert out["engines"] == {"vllm:m": "vllm-metal"}
    if sys.platform == "darwin":
        assert out["levels"][0]["peak_bytes"] > 0


def test_serve_needs_a_vllm_spec(tmp_path, capsys):
    texts = tmp_path / "t.jsonl"
    texts.write_text('{"text": "a"}\n', encoding="utf-8")
    assert cli.main(["throughput", "--model", "q3-4b", "--texts", str(texts),
                     "--serve", "vllm-mlx"]) != 0
