"""Smoke sets auxiliary GGUFs aside itself before its phantom check, so an older deploy driver's smoke passes. #1681."""
import json
import os
import shlex
import subprocess
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from harness import cli, gguf, loopback
from harness.commands import gguf_aux
from tests import shells
from tests.test_context import QWEN3_4B
from tests.test_gguf_aux_1674 import AUX, HEAD, blk, write

REPO = Path(__file__).resolve().parents[1]
BASH = shells.resolve("bash")
needs_bash = pytest.mark.skipif(sys.platform == "win32" or BASH is None, reason="runs scripts/smoke.sh lines in bash")
DRAFTER = "dspark-M-Q8_0.gguf"


def _router_lines() -> str:
    """smoke.sh from its repair through the phantom check, as smoke runs them."""
    lines = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("REPAIR="))
    check = next(i for i, ln in enumerate(lines) if "harness.router phantoms" in ln)
    end = next(i for i in range(check, len(lines)) if lines[i].strip() == "esac")
    return "\n".join(lines[start:end + 1])


@pytest.fixture
def router(tmp_path, monkeypatch):
    """A router that lists its models dir as of its last (re)start, plus any `ghosts`."""
    models = tmp_path / "hf" / "gguf"
    models.mkdir(parents=True)
    state = {"listed": [], "ghosts": [], "restarts": 0}

    def snapshot():
        # The preset writes no section for an auxiliary file, so the router lists it with no --model (#1674).
        state["listed"] = [(p.stem, "" if gguf.auxiliary(p) else str(p)) for p in sorted(models.glob("*.gguf"))]
        state["listed"] += state["ghosts"]

    class Router(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/restart":
                state["restarts"] += 1
                snapshot()
                body = {}
            elif self.path == "/health":
                body = {"status": "ok"}
            else:
                body = {"data": [{"id": stem, "source": "preset",
                                  "status": {"value": "unloaded",
                                             "args": ["llama-server", *(["--model", path] if path else [])]}}
                                 for stem, path in state["listed"]]}
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            return None

    srv = loopback.ThreadingHTTPServer(("127.0.0.1", 0), Router)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(models))
    monkeypatch.setenv("LLAMACPP_PORT", str(srv.server_address[1]))
    yield types.SimpleNamespace(models=models, state=state, snapshot=snapshot, port=srv.server_address[1])
    srv.shutdown()


def _smoke(router, tmp_path, repair=True):
    """The router lines of smoke.sh; the repair is the real verb with only its launchd restart pointed at the fake."""
    shim = tmp_path / "repair.py"
    shim.write_text(
        "import sys, urllib.request\n"
        "from harness import cli, gguf\n"
        f"gguf.refresh_router = lambda *a, **k: urllib.request.urlopen('http://127.0.0.1:{router.port}/restart')"
        ".read() and ''\n"
        "sys.exit(cli.main(['gguf-aux', '--apply']))\n", encoding="utf-8")
    script = "FAIL=0\nok(){ printf 'PASS  %s\\n' \"$1\"; }\nno(){ printf 'FAIL  %s\\n' \"$1\"; FAIL=1; }\n" \
             + _router_lines() + "\nexit $FAIL\n"
    env = {**os.environ, "PYTHONPATH": str(REPO),
           "SMOKE_REPAIR": f"{shlex.quote(sys.executable)} {shlex.quote(str(shim))}" if repair else "true"}
    return subprocess.run([BASH, "-c", script], cwd=REPO, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)


def _with_drafter(router):
    meta, tensors, _ = AUX[DRAFTER]
    write(router.models / DRAFTER, meta, tensors)
    write(router.models / "Model.gguf", QWEN3_4B, HEAD + blk(range(36)))
    router.snapshot()


@needs_bash
def test_smoke_sets_a_drafter_aside_restarts_the_router_and_passes_the_phantom_check(router, tmp_path):
    _with_drafter(router)
    got = _smoke(router, tmp_path)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "PASS  router advertises only models with a file" in got.stdout
    assert f"note    {DRAFTER}: a speculative drafter (architecture dflash)" in got.stdout
    assert [p.name for p in router.models.iterdir()] == ["Model.gguf"]
    assert [p.name for p in gguf.quarantine_dir().iterdir()] == [DRAFTER]
    assert router.state["restarts"] == 1


@needs_bash
def test_without_the_repair_the_same_drafter_is_the_deploy_22_phantom(router, tmp_path):
    """Control: the fake router reproduces deploy 22, so the pass above is the repair's."""
    _with_drafter(router)
    got = _smoke(router, tmp_path, repair=False)
    assert got.returncode == 1 and "FAIL  router advertises models with no file" in got.stdout
    assert "is a speculative drafter (architecture dflash), not a model" in got.stdout


@needs_bash
def test_a_phantom_that_is_no_auxiliary_file_still_fails(router, tmp_path):
    write(router.models / "Model.gguf", QWEN3_4B, HEAD + blk(range(36)))
    router.state["ghosts"] = [("Gone-Q4_K_M", str(router.models / "Gone-Q4_K_M.gguf"))]
    router.snapshot()
    got = _smoke(router, tmp_path)
    assert got.returncode == 1, got.stdout
    assert "FAIL  router advertises models with no file" in got.stdout and "Gone-Q4_K_M" in got.stdout
    assert router.state["restarts"] == 0 and "note" not in got.stdout


def test_smoke_runs_the_repair_verb_before_its_phantom_check_whoever_calls_it():
    """An older deploy driver runs no repair step; the new release's smoke.sh does, in its own tree."""
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("REPAIR="))
    default = line.split(":-", 1)[1].rsplit("}", 1)[0].split()
    assert default[:4] == ["uv", "run", "--quiet", "python"] and default[4:6] == ["-m", "harness.cli"]
    args = cli.build_parser().parse_args(default[6:])
    assert args.func is gguf_aux.cmd_gguf_aux and args.apply
    assert text.index(line) < text.index("harness.router phantoms") and "$REPAIR" in _router_lines()
