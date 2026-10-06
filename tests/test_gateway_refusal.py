"""A real LiteLLM proxy answers a missing or wrong key with 401 naming `soh gateway key`. #501."""
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml

from harness import gateway

REPO = Path(__file__).resolve().parents[1]
KEY = "sk-test-501"
STARTUP_S = 180.0


def _pin() -> str:
    text = (REPO / "scripts" / "versions.sh").read_text(encoding="utf-8")
    return re.search(r'^LITELLM_PIN="([^"]+)"', text, re.M).group(1)


def _launcher() -> list[str]:
    """This interpreter when it has LiteLLM, else the pinned one through uv, offline."""
    probe = "import litellm.proxy.proxy_cli"
    if subprocess.run([sys.executable, "-c", probe], capture_output=True).returncode == 0:
        return [sys.executable]
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "run", "--offline", "--no-project", "--python", "3.12",
               "--with", _pin(), "python"]
        if subprocess.run(cmd + ["-c", probe], capture_output=True,
                          timeout=300).returncode == 0:
            return cmd
    pytest.skip("LiteLLM is not importable here, nor installable offline through uv")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    where = tmp_path_factory.mktemp("gateway")
    served = gateway.served(REPO / "gateway" / "config.yaml", defaults={})
    # schema_guard reaches into the repo for harness; only the auth hook is under test.
    served.get("litellm_settings", {}).pop("callbacks", None)
    (where / "config.served.yaml").write_text(yaml.safe_dump(served), encoding="utf-8")
    for f in (REPO / "gateway").glob("*.py"):
        if f.name != "schema_guard.py":
            shutil.copy(f, where / f.name)
    port = _free_port()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LITELLM_", "DATABASE_URL", "SOHOT_"))}
    env.update(LITELLM_MASTER_KEY=KEY, LITELLM_LOCAL_MODEL_COST_MAP="True",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    log = open(where / "litellm.log", "w", encoding="utf-8")
    code = ("import sys; from litellm.proxy.proxy_cli import run_server; "
            "sys.argv[0] = 'litellm'; run_server()")
    p = subprocess.Popen(_launcher() + ["-c", code, "--config", str(where / "config.served.yaml"),
                                        "--host", "127.0.0.1", "--port", str(port),
                                        "--telemetry", "False"],
                         cwd=where, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + STARTUP_S
    try:
        while True:
            if p.poll() is not None:
                pytest.fail("LiteLLM exited during startup:\n"
                            + (where / "litellm.log").read_text(encoding="utf-8")[-3000:])
            try:
                if httpx.get(f"{base}/v1/models", timeout=5,
                             headers={"Authorization": f"Bearer {KEY}"}).status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("LiteLLM did not start within %ss" % STARTUP_S)
            time.sleep(0.5)
        yield base
    finally:
        p.terminate()
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
        log.close()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"},
                                     {"x-api-key": "wrong"}, {"Authorization": ""}],
                         ids=["missing", "wrong-bearer", "wrong-x-api-key", "empty"])
def test_a_missing_or_wrong_key_is_401_naming_the_command(proxy, headers):
    r = httpx.get(f"{proxy}/v1/models", headers=headers, timeout=10)
    assert r.status_code == 401, r.text
    assert "soh gateway key" in r.text


@pytest.mark.parametrize("headers", [{"Authorization": f"Bearer {KEY}"}, {"x-api-key": KEY}],
                         ids=["bearer", "x-api-key"])
def test_the_right_key_is_200(proxy, headers):
    r = httpx.get(f"{proxy}/v1/models", headers=headers, timeout=10)
    assert r.status_code == 200, r.text
    assert "local-small" in r.text


def test_a_refused_completion_never_reaches_a_model(proxy):
    r = httpx.post(f"{proxy}/v1/chat/completions", headers={"Authorization": "Bearer wrong"},
                   json={"model": "local-small", "messages": [{"role": "user", "content": "x"}]},
                   timeout=10)
    assert r.status_code == 401, r.text


def test_liveliness_needs_no_key(proxy):
    """scripts/services.sh probes it bare."""
    assert httpx.get(f"{proxy}/health/liveliness", timeout=10).status_code == 200


def test_backlog_takes_the_key_and_refuses_without_it(proxy):
    """gateway_switch reads it with the key."""
    ok = httpx.get(f"{proxy}/health/backlog", timeout=10,
                   headers={"Authorization": f"Bearer {KEY}"})
    assert ok.status_code == 200 and "in_flight_requests" in ok.json()
    assert httpx.get(f"{proxy}/health/backlog", timeout=10).status_code == 401
