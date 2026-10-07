"""mlx_lm.server listens with a backlog of 5; concurrent gateway clients past it were reset. #542."""
import http.server
import inspect
import re
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from harness import gateway, mlx_server, serving

REPO = Path(__file__).resolve().parents[1]
IN_FLIGHT = 32


def _connect_all(port: int, n: int = IN_FLIGHT) -> list[str]:
    """n clients connect and send a request line at once; what each saw."""
    def one(_):
        s = socket.socket()
        s.settimeout(3)
        try:
            s.connect(("127.0.0.1", port))
            s.sendall(b"POST /v1/chat/completions HTTP/1.1\r\n\r\n")
            return "ok"
        except OSError as exc:
            return type(exc).__name__
        finally:
            s.close()
    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(one, range(n)))


def _busy_server():
    """A ThreadingHTTPServer built as mlx_lm.server builds it, whose accept loop has not run yet."""
    return http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS resets past the backlog")
def test_the_stock_backlog_resets_concurrent_clients(monkeypatch):
    """The control: the defect reproduced with the class mlx_lm.server uses, unpatched."""
    monkeypatch.setattr(http.server.ThreadingHTTPServer, "request_queue_size", 5)
    srv = _busy_server()
    try:
        got = _connect_all(srv.server_address[1])
    finally:
        srv.server_close()
    assert got.count("ok") < IN_FLIGHT


def test_the_wrapper_raises_the_backlog_so_no_client_is_reset(monkeypatch):
    monkeypatch.setattr(http.server.ThreadingHTTPServer, "request_queue_size", 5)
    mlx_server.raise_backlog()
    assert http.server.ThreadingHTTPServer.request_queue_size == mlx_server.BACKLOG >= 128
    srv = _busy_server()
    try:
        got = _connect_all(srv.server_address[1])
    finally:
        srv.server_close()
    assert got == ["ok"] * IN_FLIGHT


def test_the_installed_mlx_lm_serves_with_the_class_the_wrapper_raises():
    """The seam: if mlx-lm changes its server class, the raised backlog reaches nothing."""
    server = pytest.importorskip("mlx_lm.server")
    default = inspect.signature(server._run_http_server).parameters["server_class"].default
    assert default is http.server.ThreadingHTTPServer
    assert mlx_server.ENTRY is server.main


def test_serve_mlx_execs_the_wrapper_around_mlx_lm_server():
    text = (REPO / "scripts" / "serve-mlx.sh").read_text(encoding="utf-8")
    started = re.search(r"exec\s+uv\s+run\s+python\s+-m\s+(\S+)", text)
    assert started and started.group(1) == "harness.mlx_server"
    assert mlx_server.WRAPS == serving.DEFAULT


def test_the_served_gateway_config_queues_mlx_requests_at_the_gateway(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"model_list": [
        {"model_name": "q3-4b", "litellm_params": {
            "model": "openai/mlx-community/Qwen3-4B", "api_base": f"{serving.MLX_URL}/v1"}},
        {"model_name": "own-cap", "litellm_params": {
            "model": "openai/m", "api_base": f"{serving.MLX_URL}/v1",
            "max_parallel_requests": 3}},
        {"model_name": "eval-7b", "litellm_params": {
            "model": "openai/x", "api_base": f"{serving.LLAMACPP_URL}/v1"}},
    ]}), encoding="utf-8")
    got = {e["model_name"]: e["litellm_params"]
           for e in gateway.served(cfg, defaults={"code": "q3-4b"})["model_list"]}
    assert got["q3-4b"]["max_parallel_requests"] == serving.MLX_MAX_PARALLEL
    assert got["sohot-code"]["max_parallel_requests"] == serving.MLX_MAX_PARALLEL
    assert got["own-cap"]["max_parallel_requests"] == 3
    assert "max_parallel_requests" not in got["eval-7b"]
    assert serving.MLX_MAX_PARALLEL <= mlx_server.BACKLOG
