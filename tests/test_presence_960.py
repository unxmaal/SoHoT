"""One answer per engine to "is it here": vLLM (#960), llama.cpp (#1449). Every caller asks the same function."""
import os
import socket
import sys
import textwrap

import pytest

import fakes
from evals import run as R
from harness import inspect as ins
from harness import llama_vlm, machine, paths, rank, screen, serving, vllm

REPO = "mistralai/Mistral-7B-Instruct-v0.3"
NEEDS_VLLM = {"name": REPO, "lane": "code", "runtime_needed": "vllm"}
POSIX = pytest.mark.skipif(sys.platform == "win32", reason="an extensionless script is not executable there")


def _exe(path, body="#!/bin/sh\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _seed(engine="vllm-mlx", body="#!/bin/sh\n"):
    """A vLLM venv where harness/vllm.py serves from: <home>/venvs/<engine>."""
    venv = paths.home() / "venvs" / engine
    (venv / "lib" / "python3.12" / "site-packages" / f"{engine.replace('-', '_')}-0.5.0.dist-info").mkdir(parents=True)
    return _exe(vllm.binary(engine, venv), body)


@pytest.fixture(autouse=True)
def _vllm_env(monkeypatch):
    for var in (vllm.VENV_VAR, serving.VLLM_ENGINE_VAR, serving.VLLM_PORT_VAR, "LLAMACPP_BIN"):
        monkeypatch.delenv(var, raising=False)
    for name in machine._RUNTIME_PROBES:
        if name not in ("vllm", "llamacpp"):
            monkeypatch.setitem(machine._RUNTIME_PROBES, name, lambda: False)
    machine.detect.cache_clear()
    yield
    machine.detect.cache_clear()


def _detected():
    machine.detect.cache_clear()
    return machine.detect()


def _answers() -> dict:
    """What each caller says about vLLM on this machine."""
    return {
        "vllm.available": bool(vllm.available()),
        "machine._has_vllm": machine._has_vllm(),
        "machine.refuses": _detected().refuses("vllm") is None,
        "rank.unrunnable": rank.unrunnable(NEEDS_VLLM, _detected()) == "",
        "screen.runner_gap": screen.runner_gap("code", REPO, card=NEEDS_VLLM) == "",
        "evals.run._servable": _servable(f"{serving.VLLM_PREFIX}{REPO}"),
    }


def _servable(spec) -> bool:
    try:
        R._servable(spec)
    except SystemExit:
        return False
    return True


def test_a_seeded_vllm_venv_is_vllm_to_every_caller():
    """#960 acceptance: on main machine.refuses("vllm") said needs-vllm with this venv in place."""
    exe = _seed()
    assert set(_answers().values()) == {True}, _answers()
    assert vllm.argv("vllm-mlx", REPO, 8086)[0] == str(exe)
    assert vllm.venv_for("vllm-mlx") in machine._vllm_venvs()
    assert machine._site_versions(vllm.venv_for("vllm-mlx"))["vllm-mlx"] == "0.5.0"


def test_without_one_no_caller_has_vllm():
    assert set(_answers().values()) == {False}, _answers()
    assert screen.runner_gap("code", REPO, card=NEEDS_VLLM).startswith("needs-vllm: ")


def test_a_vllm_on_path_is_not_one_the_harness_starts(tmp_path, monkeypatch):
    """vllm.argv never execs a PATH vllm, so finding one there is not having vLLM."""
    _exe(tmp_path / "bin" / ("vllm.exe" if sys.platform == "win32" else "vllm"))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert set(_answers().values()) == {False}, _answers()


def test_the_selected_engine_decides(monkeypatch):
    _seed("vllm-mlx")
    monkeypatch.setenv(serving.VLLM_ENGINE_VAR, "vllm-metal")
    assert set(_answers().values()) == {False}, _answers()
    _seed("vllm-metal")
    assert set(_answers().values()) == {True}, _answers()
    assert vllm.available() == "vllm-metal"


@POSIX
def test_a_venv_whose_executable_cannot_run_is_not_vllm():
    _seed().chmod(0o644)
    assert set(_answers().values()) == {False}, _answers()


def _consolidated_only() -> dict:
    card = fakes.card(REPO)
    card["siblings"] = [s for s in card["siblings"] if not s["rfilename"].startswith("model")
                        and s["rfilename"] != "config.json"]
    return {"name": REPO, "lane": "code", "runtime_needed": ins.card_facts(card).runtime_needed}


def test_a_consolidated_only_listing_screens_as_vllm_and_never_reaches_mlx_lm():
    """#947's negative control on a machine with vLLM: the screen runs it on the vLLM server."""
    row = _consolidated_only()
    assert row["runtime_needed"] == "vllm"
    _seed()
    [got] = screen.plan([row], missing=lambda t: [])
    assert got["state"] == screen.READY, got["why_not"]
    assert got["candidate"] == f"{serving.VLLM_PREFIX}{REPO}"
    argv = screen.argv(got)
    assert argv[argv.index("--candidates") + 1] == f"{serving.VLLM_PREFIX}{REPO}"
    assert REPO not in argv
    assert serving.route(got["candidate"]).base == serving.vllm_url()


def test_without_vllm_the_same_listing_is_our_gap_not_a_screen():
    [got] = screen.plan([_consolidated_only()], missing=lambda t: [])
    assert got["state"] == screen.NO_RUNNER
    assert got["why_not"].startswith("needs-vllm: ")


def test_a_lane_vllm_does_not_serve_is_a_gap_not_a_run_on_its_own_runner():
    _seed()
    row = {**NEEDS_VLLM, "lane": "stt"}
    assert not screen.candidate_for("stt", REPO, card=row).startswith(serving.VLLM_PREFIX)
    assert screen.runner_gap("stt", REPO, card=row).startswith("needs vllm, which serves only")


def test_a_caller_holding_only_the_store_routes_and_gaps_alike(tmp_path):
    """fetching.run and the coverage/measure readers pass conn, not a row."""
    from harness import memory_store as ms
    card = fakes.card(REPO)
    card["siblings"] = [s for s in card["siblings"] if not s["rfilename"].startswith("model")
                        and s["rfilename"] != "config.json"]
    conn = ms.connect(tmp_path / "s.db")
    fakes.seeded_store(conn, [(REPO, "code", 14.0, 1)])
    fakes.carded(conn, REPO, card)
    assert ms.card_of(conn, REPO)["runtime_needed"] == "vllm"
    assert screen.candidate_for("code", REPO, conn=conn) == f"{serving.VLLM_PREFIX}{REPO}"
    assert screen.runner_gap("code", REPO, conn=conn).startswith("needs-vllm: ")
    _seed()
    assert screen.runner_gap("code", REPO, conn=conn) == ""


def test_pairing_a_vllm_candidate_runs_it_whole():
    assert R.pair_block([REPO, f"{serving.VLLM_PREFIX}{REPO}"], "") is None


SERVER = textwrap.dedent("""\
    #!{python}
    import json, sys
    from http.server import BaseHTTPRequestHandler
    from socketserver import TCPServer
    port = int(sys.argv[sys.argv.index("--port") + 1])
    model = sys.argv[2]
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            body = json.dumps({{"data": [{{"id": model}}]}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    TCPServer(("127.0.0.1", port), H).serve_forever()
    """)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@POSIX
def test_a_screen_starts_the_vllm_server_it_names_and_stops_it(monkeypatch):
    port = _free_port()
    monkeypatch.setenv(serving.VLLM_PORT_VAR, str(port))
    _seed(body=SERVER.format(python=sys.executable))
    spec = f"{serving.VLLM_PREFIX}{REPO}"
    with R._served(spec) as launched:
        assert launched is None
        listed = []
        assert vllm._probe(serving.vllm_url(), listed) == "" and listed == [REPO]
    assert vllm._probe(serving.vllm_url()) != ""
    log = paths.home() / "logs" / f"vllm-mlx-{port}.log"
    assert log.is_file()


def test_a_server_already_up_for_another_model_is_refused_not_used(monkeypatch):
    from http.server import BaseHTTPRequestHandler
    import json
    import threading

    from harness.loopback import ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"data": [{"id": "other/model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv(serving.VLLM_PORT_VAR, str(srv.server_address[1]))
        with pytest.raises(SystemExit, match="is not served: .* serves other/model, not "):
            with R._served(f"{serving.VLLM_PREFIX}{REPO}"):
                pass
    finally:
        srv.shutdown()
        srv.server_close()


# ---- llama.cpp (#1449) ------------------------------------------------------

def _path(monkeypatch, tmp_path, *names):
    d = tmp_path / "bin"
    for n in names:
        _exe(d / (n + (".exe" if sys.platform == "win32" else "")))
    monkeypatch.setenv("PATH", str(d))
    return d


def _llama_answers() -> dict:
    return {
        "serving.llamacpp_binary": serving.llamacpp_binary() is not None,
        "machine._has_llamacpp": machine._has_llamacpp(),
        "machine.refuses": _detected().refuses("llamacpp") is None,
    }


def test_llama_cli_alone_is_no_llama_server(monkeypatch, tmp_path):
    _path(monkeypatch, tmp_path, "llama-cli")
    assert set(_llama_answers().values()) == {False}, _llama_answers()


def test_a_stale_llamacpp_bin_is_absent_to_every_caller_though_path_has_one(monkeypatch, tmp_path):
    _path(monkeypatch, tmp_path, "llama-server")
    gone = tmp_path / "gone" / "llama-server"
    monkeypatch.setenv("LLAMACPP_BIN", str(gone))
    assert set(_llama_answers().values()) == {False}, _llama_answers()
    assert llama_vlm.argv_for(tmp_path / "m.gguf", tmp_path / "p.gguf", 1)[0] == str(gone)


@POSIX
def test_a_llamacpp_bin_that_cannot_run_is_absent(monkeypatch, tmp_path):
    _path(monkeypatch, tmp_path)
    named = _exe(tmp_path / "llama-server")
    named.chmod(0o644)
    monkeypatch.setenv("LLAMACPP_BIN", str(named))
    assert set(_llama_answers().values()) == {False}, _llama_answers()


def test_a_named_llamacpp_bin_is_what_every_caller_runs(monkeypatch, tmp_path):
    _path(monkeypatch, tmp_path, "llama-server")
    named = _exe(tmp_path / "own" / ("llama-server" + (".exe" if sys.platform == "win32" else "")))
    monkeypatch.setenv("LLAMACPP_BIN", str(named))
    assert set(_llama_answers().values()) == {True}, _llama_answers()
    assert os.path.samefile(serving.llamacpp_binary(), named)
    assert os.path.samefile(llama_vlm.argv_for(tmp_path / "m.gguf", tmp_path / "p.gguf", 1)[0], named)


def test_llama_server_on_path_is_what_every_caller_runs(monkeypatch, tmp_path):
    d = _path(monkeypatch, tmp_path, "llama-server")
    assert set(_llama_answers().values()) == {True}, _llama_answers()
    assert os.path.dirname(llama_vlm.argv_for(tmp_path / "m.gguf", tmp_path / "p.gguf", 1)[0]) == str(d)
