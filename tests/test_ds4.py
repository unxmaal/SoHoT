"""antirez/ds4 (DwarfStar) as an engine: spec, route, service, launch receipt, inspect, memory. #611."""
import argparse
import dataclasses
import json
import os
import re
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import shells
from evals import core, environment
from evals import run as R
from evals.core import Case, Receipt, Result
from harness import (context, downloads, ds4, fetching, gateway, gguf, machine,
                     paired, reverify, screen, serving)
from harness import inspect as ins
from harness import memory as mem
from harness import memory_store as ms

REPO = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).resolve().parent / "fake_ds4_server.py"
GIB = 1024 ** 3
QWEN = "antirez/qwen3.8-flash-next-gguf"
QWEN_Q2 = "Qwen3.8-Flash-Next-Q2"
DSV4 = "antirez/deepseek-v4-gguf"
DSV4_Q2 = "DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix-0731"


def sib(name, gib):
    return {"rfilename": name, "size": int(gib * GIB)}


QWEN_CARD = {"tags": ["gguf", "qwen4exp", "text-generation"],
             "pipeline_tag": "text-generation",
             "siblings": [sib("README.md", 0.0001), sib("Qwen3.8-Flash-Next-Q2.gguf", 137.10),
                          sib("Qwen3.8-Flash-Next-Q4.gguf", 165.11)]}
DSV4_CARD = {"library_name": "gguf", "tags": ["gguf", "deepseek-v4"],
             "pipeline_tag": "text-generation",
             "siblings": [sib(f"{DSV4_Q2}.gguf", 80.76),
                          sib("DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf", 3.55)]}
GENERAL_CARD = {"tags": ["gguf", "image-text-to-text"], "pipeline_tag": "text-generation",
                "siblings": [sib("Qwen3.8-Flash-Next-Q4_K_M.gguf", 60.0)]}


def _here(*runtimes):
    return dataclasses.replace(machine.detect(), runtimes=frozenset({"cpu", *runtimes}))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def models(tmp_path, monkeypatch):
    """A ds4 models dir holding empty stand-ins for the GGUFs, and the fake server as the binary."""
    d = tmp_path / "ds4-models"
    d.mkdir()
    for stem in (QWEN_Q2, DSV4_Q2):
        (d / f"{stem}.gguf").write_bytes(b"GGUF")
    monkeypatch.setenv(ds4.MODELS_VAR, str(d))
    ds4.checkout().mkdir(parents=True)
    monkeypatch.setattr(ds4, "binary", lambda: [sys.executable, str(FAKE)])
    monkeypatch.setattr(ds4, "version", lambda: "2026.09.20")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    port = _free_port()
    monkeypatch.setenv(ds4.PORT_VAR, str(port))
    return d


# ---- the spec ---------------------------------------------------------------

def test_a_ds4_spec_routes_to_ds4_server_whatever_the_gateway(monkeypatch):
    monkeypatch.delenv(ds4.PORT_VAR, raising=False)
    got = serving.route(f"ds4:{QWEN_Q2},temperature=0", gateway="http://127.0.0.1:4000")
    assert got == serving.Route(ds4.URL, QWEN_Q2, {"temperature": 0.0})
    monkeypatch.setenv(ds4.PORT_VAR, "18611")
    assert serving.route(f"ds4:{QWEN_Q2}").base == "http://127.0.0.1:18611"


def test_server_options_are_not_sampling_and_do_not_reach_the_request():
    got = serving.route(f"ds4:{DSV4_Q2},ssd_streaming=on,expert_cache=32GB,ctx=8192")
    assert got.sampling == {}
    assert got.model == DSV4_Q2


@pytest.mark.parametrize("spec, why", [
    ("ds4:", "names no model"),
    (f"ds4:{QWEN_Q2},flavour=on", "unknown option"),
    (f"ds4:{DSV4_Q2},expert_cache=32GB", "expert_cache needs ssd_streaming=on"),
    (f"ds4:{DSV4_Q2},ssd_streaming=maybe", "ssd_streaming must be on or off"),
    (f"ds4:{QWEN_Q2},ssd_streaming=on", "not implemented"),
    (f"ds4:{QWEN_Q2},ctx=0", "ctx must be a positive"),
    (f"ds4:{DSV4_Q2},ssd_streaming=on,expert_cache=lots", "expert_cache"),
])
def test_a_bad_ds4_spec_is_refused_before_anything_loads(spec, why):
    with pytest.raises(ValueError, match=why):
        ds4.parse(spec)
    with pytest.raises(ValueError):
        serving.route(spec)


def test_ds4_is_a_text_engine_with_its_own_label(tmp_path, monkeypatch):
    monkeypatch.delenv(ds4.PORT_VAR, raising=False)
    assert serving.text_spec(f"ds4:{QWEN_Q2}")
    assert R.kind_of(f"ds4:{QWEN_Q2},ssd_streaming=off") == "ds4"
    assert serving.engine_for(f"ds4:{QWEN_Q2}") == "ds4-server"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""\
        model_list:
          - model_name: flash
            litellm_params:
              model: openai/{QWEN_Q2}
              api_base: {ds4.URL}/v1
        """), encoding="utf-8")
    assert serving.engine_for("flash", environ={}, config=cfg) == "ds4-server"
    assert not serving.enforces_schema(f"ds4:{QWEN_Q2}")


def test_the_generated_gateway_config_fronts_a_ds4_adoption(tmp_path, monkeypatch):
    monkeypatch.delenv(ds4.PORT_VAR, raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model_list: []\n", encoding="utf-8")
    got = gateway.served(cfg, defaults={"code": f"ds4:{QWEN_Q2}", "agent": f"ds4:{QWEN_Q2}"})
    by = {e["model_name"]: e["litellm_params"] for e in got["model_list"]}
    assert by["sohot-code"]["api_base"] == f"{ds4.URL}/v1"
    assert by["sohot-agent"]["model"] == f"openai/{QWEN_Q2}"


def test_streaming_is_one_receipt_key_and_two_launches():
    """One ds4-server holds one launch, so on and off are two runs, not two rows of one."""
    on = R.build_runner(f"ds4:{DSV4_Q2},ssd_streaming=on", "http://gw", None)
    off = R.build_runner(f"ds4:{DSV4_Q2}", "http://gw", None)
    assert on.candidate == off.candidate == f"ds4:{DSV4_Q2}"
    assert ds4.launch(f"ds4:{DSV4_Q2},ssd_streaming=on") != ds4.launch(f"ds4:{DSV4_Q2}")


def test_server_options_are_not_recorded_as_sampling():
    got = R.effective_sampling("code", [f"ds4:{DSV4_Q2},ssd_streaming=on,expert_cache=32GB,"
                                        f"temperature=0"])
    assert got["code"]["temperature"] == 0.0
    assert "ssd_streaming" not in got["code"] and "expert_cache" not in got["code"]


# ---- the launch -------------------------------------------------------------

def test_the_argv_names_the_file_the_context_and_streaming(models, monkeypatch):
    monkeypatch.setattr(ds4, "binary", lambda: ["/x/ds4-server"])
    off = ds4.argv(f"ds4:{QWEN_Q2},ctx=8192", 9001)
    assert off[0] == "/x/ds4-server"
    assert off[off.index("-m") + 1] == str(models / f"{QWEN_Q2}.gguf")
    assert off[off.index("--ctx") + 1] == "8192"
    assert off[off.index("--port") + 1] == "9001"
    assert off[off.index("--host") + 1] == "127.0.0.1"
    assert "--chdir" in off
    assert "--ssd-streaming" not in off
    on = ds4.argv(f"ds4:{DSV4_Q2},ssd_streaming=on,expert_cache=32GB", 9001)
    assert "--ssd-streaming" in on
    assert on[on.index("--ssd-streaming-cache-experts") + 1] == "32GB"
    assert on[on.index("--ctx") + 1] == str(ds4.DEFAULT_CTX)


def test_the_launch_record_names_every_option_that_changes_the_exam(models):
    got = ds4.launch(f"ds4:{DSV4_Q2},ssd_streaming=on,expert_cache=32GB,temperature=0")
    assert got == {"ssd_streaming": "on", "expert_cache": "32GB",
                   "ctx": ds4.DEFAULT_CTX, "ds4": "2026.09.20"}
    assert ds4.launch(f"ds4:{QWEN_Q2}")["expert_cache"] == "auto"
    assert ds4.launch_text(got) == "ctx=32768,ds4=2026.09.20,expert_cache=32GB,ssd_streaming=on"


def test_the_launcher_execs_exactly_what_the_harness_would_start(models, monkeypatch):
    """serve-ds4.sh reads its argv from `python -m harness.ds4 argv`, never its own copy."""
    monkeypatch.setattr(ds4, "binary", lambda: ["/x/ds4-server"])
    import io
    out = io.StringIO()
    assert ds4.main(["argv", f"ds4:{QWEN_Q2}", "--port", "9002", "--pid", "4242"], out=out) == 0
    assert out.getvalue().splitlines() == ds4.argv(f"ds4:{QWEN_Q2}", 9002)
    state = json.loads(ds4.state_path(9002).read_text(encoding="utf-8"))
    assert state["pid"] == 4242 and state["spec"] == f"ds4:{QWEN_Q2}"
    assert state["launch"] == ds4.launch(f"ds4:{QWEN_Q2}")
    script = (REPO / "scripts" / "serve-ds4.sh").read_text(encoding="utf-8")
    assert "harness.ds4 argv" in script and "exec" in script


def test_the_service_lives_where_the_harness_looks_for_it():
    services = (REPO / "scripts" / "services.sh").read_text(encoding="utf-8")
    assert re.search(r'ds4\)\s+printf .%s\\n. "scripts/serve-ds4.sh"', services)
    port = re.search(r'ds4\)\s+printf .%s\\n. "\$\{DS4_PORT:-(\d+)\}"', services)
    assert port and f"127.0.0.1:{port.group(1)}" == ds4.URL.removeprefix("http://")
    launchd = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    assert "ds4" in re.search(r'^SERVICES="([^"]+)"', launchd, re.M).group(1).split()


def test_with_nothing_to_serve_the_service_exits_cleanly_and_says_why(tmp_path):
    env = {**os.environ, "DS4_SPEC": "", "LOCALHARNESS_HOME": str(tmp_path)}
    proc = subprocess.run([shells.BASH, str(REPO / "scripts" / "serve-ds4.sh")],
                          capture_output=True, text=True, env=env, cwd=REPO,
                          encoding="utf-8", timeout=120,
                          input="")
    assert proc.returncode == 0, proc.stderr
    assert "nothing to serve" in proc.stdout + proc.stderr


def test_launchd_does_not_restart_a_service_that_had_nothing_to_serve(tmp_path):
    import plistlib
    out = tmp_path / "plists"
    subprocess.run([shells.BASH, str(REPO / "scripts" / "launchd.sh"), "generate", str(out)],
                   check=True, capture_output=True)
    unit = plistlib.loads(next(out.glob("*.ds4.plist")).read_bytes())
    assert unit["KeepAlive"] == {"SuccessfulExit": False}


# ---- serving with a fake ds4-server ----------------------------------------

def test_a_run_starts_ds4_server_for_its_spec_and_stops_it(models):
    spec = f"ds4:{DSV4_Q2},ssd_streaming=on,expert_cache=32GB"
    with ds4.serving(spec, timeout=30) as got:
        assert got["launch"] == ds4.launch(spec)
        assert ds4.live()["spec"] == spec
        pid = got["pid"]
        assert ds4.alive(pid)
    assert not ds4.alive(pid)
    assert ds4.live() is None
    log = (Path(os.environ["LOCALHARNESS_HOME"]) / "logs").glob("ds4-*.log")
    assert "streaming=True cache=32GB" in next(log).read_text(encoding="utf-8")


def test_a_live_server_with_the_same_launch_is_reused(models):
    spec = f"ds4:{QWEN_Q2}"
    with ds4.serving(spec, timeout=30) as first:
        with ds4.serving(f"{spec},temperature=0", timeout=30) as again:
            assert again["pid"] == first["pid"]
        assert ds4.alive(first["pid"]), "the inner run stopped a server it did not start"


def test_a_server_holding_another_launch_is_refused_not_replaced(models):
    with ds4.serving(f"ds4:{DSV4_Q2}", timeout=30):
        with pytest.raises(ds4.Unservable, match="ssd_streaming=on.*serves|serves.*ssd_streaming=off"):
            with ds4.serving(f"ds4:{DSV4_Q2},ssd_streaming=on", timeout=30):
                pass


def test_a_server_nobody_recorded_is_refused(models):
    """Answering /v1/models proves something is up, not which model or flags it holds."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = b'{"data": [{"id": "deepseek-v4-flash"}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", int(os.environ[ds4.PORT_VAR])), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(ds4.Unservable, match="not started by this harness"):
            ds4.preflight(f"ds4:{QWEN_Q2}")
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_missing_model_file_or_binary_is_named_before_anything_starts(models, monkeypatch):
    with pytest.raises(ds4.Unservable, match="python -m harness.ds4 fetch"):
        ds4.preflight("ds4:Not-Downloaded-Q2")
    monkeypatch.setattr(ds4, "binary", lambda: [str(models / "no-such-ds4-server")])
    with pytest.raises(ds4.Unservable, match="scripts/ds4-build.sh"):
        ds4.preflight(f"ds4:{QWEN_Q2}")


def test_the_served_context_is_read_from_the_server(models):
    with ds4.serving(f"ds4:{QWEN_Q2},ctx=8192", timeout=30):
        assert context.served_ctx(f"ds4:{QWEN_Q2}") == 8192
    assert context.served_ctx(f"ds4:{QWEN_Q2},ctx=4096") == 4096


def test_an_eval_run_measures_ds4_and_records_the_launch(models, monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(core, "load_cases",
                        lambda path: [Case(id="a", modality="code", prompt="p")])
    monkeypatch.setattr(R, "warn_if_pressed",
                        lambda: argparse.Namespace(as_dict=lambda: {}))
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture",
                        lambda: {"hw_model": "Test,1", "os": "t", "arch": "a"})
    monkeypatch.setattr(core, "score", lambda case, art, **k: Result(
        case.id, "", "def f" in str(art), 0.0, 0, ""))
    log = tmp_path / "requests.jsonl"
    monkeypatch.setenv("DS4_FAKE_LOG", str(log))
    spec = f"ds4:{DSV4_Q2},ssd_streaming=on"
    args = argparse.Namespace(modality="code", candidates=spec, cases="x", out=str(out),
                              screen=False, repeat=1, adherence="", gateway="http://gw",
                              from_winners=False)
    assert R._execute(args) == 0
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    key = f"ds4:{DSV4_Q2}"
    assert data["rows"][0]["passed"]
    assert data["receipt"]["engines"] == {spec: "ds4-server"}
    assert data["receipt"]["instruments"]["serving"] == "ds4-server"
    assert data["receipt"]["launch"] == {
        key: "ctx=32768,ds4=2026.09.20,expert_cache=auto,ssd_streaming=on"}
    sent = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert sent["model"] == DSV4_Q2
    assert "ssd_streaming" not in sent
    assert ds4.live() is None, "the run left its ds4-server running"


def test_a_run_whose_ds4_cannot_be_served_stops_before_measuring(models):
    args = argparse.Namespace(modality="code", candidates="ds4:Not-Downloaded-Q2",
                              cases=str(REPO / "evals" / "cases"), out=None, screen=False,
                              repeat=1, adherence="", gateway="http://gw", from_winners=False)
    with pytest.raises(SystemExit, match="ds4"):
        R._execute(args)


# ---- comparable -------------------------------------------------------------

def _receipt(**kw):
    base = dict(modality="code", case_ids=("a",), repeat=1, sampling={}, gateway="g")
    return Receipt(**{**base, **kw})


def test_two_launches_of_one_ds4_model_are_two_exams():
    on = _receipt(launch={"ds4:m": "ctx=32768,ds4=1,expert_cache=auto,ssd_streaming=on"})
    off = _receipt(launch={"ds4:m": "ctx=32768,ds4=1,expert_cache=auto,ssd_streaming=off"})
    ok, why = core.comparable(on, off)
    assert not ok and "launch" in why and "ssd_streaming" in why
    assert core.comparable(on, on)[0]
    assert core.comparable(on, _receipt())[0], "a run that says nothing is not a mismatch"
    cache = _receipt(launch={"ds4:m": "ctx=32768,ds4=1,expert_cache=32GB,ssd_streaming=on"})
    assert not core.comparable(on, cache)[0]
    assert "launch" in paired.AXES
    assert paired.differences(on, off) == ["launch"]
    assert on.as_dict()["launch"] == on.launch


def test_compare_runs_reads_the_launch_back(tmp_path, capsys):
    files = []
    for name, streaming in (("a", "on"), ("b", "off")):
        d = tmp_path / name
        d.mkdir()
        r = _receipt(launch={"ds4:m": f"ctx=1,ds4=1,expert_cache=auto,ssd_streaming={streaming}"})
        (d / "results.json").write_text(json.dumps({"receipt": r.as_dict(), "summary": {}}),
                                        encoding="utf-8")
        files.append(str(d / "results.json"))
    assert R.compare_runs(files) == 1
    assert "launch" in capsys.readouterr().out


# ---- inspect: ds4's own GGUFs are not general GGUFs -------------------------

def test_a_ds4_repo_is_sized_by_its_resident_weights_not_its_file():
    fit = ins.inspect_model(QWEN, data=QWEN_CARD, ceiling=66 * GIB, machine=_here("ds4", "llamacpp"))
    assert fit.verdict == "fits", fit.why
    assert fit.offered == ["ds4"]
    assert not fit.gguf
    assert "41.7 GiB resident" in fit.why and "95.4 GiB" in fit.why
    assert fit.largest == int(137.10 * GIB), "the download is still the whole file"


def test_a_ds4_repo_on_a_machine_without_ds4_waits_for_ds4_not_llama():
    fit = ins.inspect_model(QWEN, data=QWEN_CARD, ceiling=66 * GIB, machine=_here("llamacpp"))
    assert fit.verdict == "needs-ds4"
    assert ins.until_of(fit) == "runtime:ds4"


def test_the_ceiling_is_held_against_resident_weights():
    fit = ins.inspect_model(QWEN, data=QWEN_CARD, ceiling=22 * GIB, machine=_here("ds4"))
    assert fit.verdict == "too-big"
    assert "41.7 GiB" in fit.why
    assert ins.until_of(fit) == "ceiling_gb:>41.7"


def test_a_model_ds4_can_stream_fits_over_the_ceiling_with_streaming():
    fit = ins.inspect_model(DSV4, data=DSV4_CARD, ceiling=66 * GIB, machine=_here("ds4"))
    assert fit.verdict == "fits", fit.why
    assert "ssd streaming" in fit.why
    assert ds4.spec_for(DSV4, DSV4_CARD["siblings"], 66 * GIB) == (
        f"ds4:{DSV4_Q2},ssd_streaming=on")
    assert ds4.spec_for(DSV4, DSV4_CARD["siblings"], 90 * GIB) == f"ds4:{DSV4_Q2}"


def test_a_general_gguf_of_the_same_model_still_goes_to_llama_server():
    repo = "ggml-org/Qwen3.8-Flash-Next-GGUF"
    assert not ds4.recognised(repo, GENERAL_CARD)
    fit = ins.inspect_model(repo, data=GENERAL_CARD, ceiling=66 * GIB,
                            machine=_here("ds4", "llamacpp"))
    assert fit.offered == ["llamacpp"]


def test_ds4s_own_architecture_tag_is_recognised_in_a_repo_not_listed():
    assert ds4.recognised("someone/qwen38-ds4-mirror", {"tags": ["gguf", "qwen4exp"]})


def test_a_file_ds4_does_not_list_is_unknown_rather_than_guessed():
    assert ds4.model_of("Qwen3.8-Flash-Next-Q2") is not None
    assert ds4.model_of("Qwen3.8-Flash-Next-Q3_K_M") is None
    card = {"tags": ["gguf"], "siblings": [sib("Mystery-Q2.gguf", 50)]}
    fit = ins.inspect_model(QWEN, data=card, ceiling=66 * GIB, machine=_here("ds4"))
    assert fit.verdict == "unknown", fit.why


# ---- the queue routes these to ds4 -----------------------------------------

@pytest.fixture
def recorded(models):
    conn = ms.connect()
    try:
        downloads.record(conn, QWEN, downloads.GGUF, models / f"{QWEN_Q2}.gguf",
                         file=f"{QWEN_Q2}.gguf")
    finally:
        conn.close()
    return models


@pytest.mark.parametrize("lane", ["code", "agent"])
def test_a_fetched_ds4_repo_is_spelled_for_ds4_not_llama_server(recorded, lane):
    assert gguf.fetched(QWEN) == QWEN_Q2, "the downloads row is what llama-server would have used"
    assert screen.candidate_for(lane, QWEN) == f"ds4:{QWEN_Q2}"
    assert serving.route(QWEN, gateway="http://127.0.0.1:4000").base == ds4.url()
    assert screen.runner_gap(lane, QWEN) == ""


def test_a_ds4_spec_passes_through_the_lane_spelling():
    spec = f"ds4:{DSV4_Q2},ssd_streaming=on"
    assert screen.candidate_for("code", spec) == spec


def test_the_decide_lane_says_why_ds4_cannot_serve_it(recorded):
    assert "response_format" in screen.runner_gap("decide", QWEN)


def test_the_memory_check_counts_main_weights_not_on_disk_ngrams(recorded, monkeypatch):
    monkeypatch.setattr(mem, "size_gb", lambda path: 137.10)
    monkeypatch.setattr(mem, "available_gb", lambda: 80.0)
    monkeypatch.setattr(mem, "ceiling_gb", lambda: 72.0)
    monkeypatch.setattr(mem, "measured_reserve_gb", lambda: 6.0)
    ok, why = mem.check_model(QWEN, spec=f"ds4:{QWEN_Q2}")
    assert ok, why
    assert why.startswith("41.7 GB")
    llama_ok, _ = mem.check_model(QWEN, spec=f"llamacpp:{QWEN_Q2}")
    assert not llama_ok, "a general GGUF is still sized by its file"


def test_with_streaming_the_memory_check_counts_the_expert_cache(monkeypatch):
    assert ds4.resident_bytes(f"ds4:{DSV4_Q2}", int(80.76 * GIB)) == int(80.76 * GIB)
    assert ds4.resident_bytes(f"ds4:{DSV4_Q2},ssd_streaming=on,expert_cache=32GB",
                              int(80.76 * GIB)) == 32 * GIB
    assert ds4.resident_bytes(f"ds4:{DSV4_Q2},ssd_streaming=on", int(80.76 * GIB)) is None
    assert ds4.resident_bytes(f"ds4:{QWEN_Q2}", int(137.10 * GIB)) == pytest.approx(
        41.73 * GIB, rel=1e-3)


def test_the_fetch_tier_never_downloads_a_ds4_model_on_its_own(tmp_path, monkeypatch):
    db = ms.connect(tmp_path / "d.db")
    ms.record(db, ms.Seen(name=QWEN, source="t", resolved=QWEN, kind="weights", lane="code"))
    ms.set_size(db, QWEN, int(137.10 * GIB))
    ms.decide(db, QWEN, "queued", tier="inspect", size_bytes=int(137.10 * GIB))
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")

    def refuse(*a, **k):
        raise AssertionError("a ds4 model was downloaded by the loop")
    done = fetching.run(db, snapshot=refuse, free=900 * GIB,
                        listing=lambda repo: QWEN_CARD["siblings"], hf_download=refuse)
    assert done and not done[0]["ok"]
    assert "python -m harness.ds4 fetch" in done[0]["why"]
    assert db.execute("SELECT state FROM proposals WHERE name = ?",
                      (QWEN,)).fetchone()["state"] == "queued"
    db.close()


def test_the_by_hand_fetch_puts_the_file_in_the_ds4_dir_and_records_it(models, monkeypatch):
    got = []

    def hf_download(repo, filename, local_dir):
        got.append((repo, filename, local_dir))
        (Path(local_dir) / filename).write_bytes(b"GGUF")
        return str(Path(local_dir) / filename)
    where = ds4.fetch(QWEN, "Qwen3.8-Flash-Next-Q4.gguf", hf_download=hf_download)
    assert got == [(QWEN, "Qwen3.8-Flash-Next-Q4.gguf", str(models))]
    assert Path(where).parent == models
    assert gguf.fetched(QWEN) == "Qwen3.8-Flash-Next-Q4"
    with pytest.raises(ValueError, match="ds4 lists"):
        ds4.fetch(QWEN, "Qwen3.8-Flash-Next-Q3_K_M.gguf", hf_download=hf_download)


# ---- the runtime, its version, and the pin ---------------------------------

def test_the_runtime_is_present_when_the_built_binary_is(tmp_path, monkeypatch):
    exe = tmp_path / "ds4-server"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setattr(ds4, "binary", lambda: [str(exe)])
    assert machine._has_ds4()
    monkeypatch.setattr(ds4, "binary", lambda: [str(tmp_path / "absent")])
    assert not machine._has_ds4()


def test_a_ds4_run_is_reverified_when_ds4_changes():
    assert reverify.runtimes_for("code", f"ds4:{QWEN_Q2}")[:1] == ("ds4",)
    assert screen.load_until(f"ds4:{QWEN_Q2}").startswith("version:ds4>")


def test_the_version_is_the_checkout_commit_date(tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-09-20T03:21:24+02:00",
           "GIT_COMMITTER_DATE": "2026-09-20T03:21:24+02:00",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "x"],
                   check=True, env=env)
    monkeypatch.setattr(ds4, "checkout", lambda: repo)
    assert ds4.version() == "2026.09.20"


def test_the_build_script_checks_out_the_pinned_commit_under_the_home():
    pins = (REPO / "scripts" / "versions.sh").read_text(encoding="utf-8")
    rev = re.search(r'^DS4_REV="([0-9a-f]{40})"$', pins, re.M)
    assert rev, "ds4 is pinned by full commit"
    assert re.search(r'^DS4_REPO_URL="https://github.com/antirez/ds4(\.git)?"$', pins, re.M)
    build = (REPO / "scripts" / "ds4-build.sh").read_text(encoding="utf-8")
    assert "versions.sh" in build and '"$DS4_REV"' in build
    assert "LOCALHARNESS_HOME" in build and "HF_HOME" not in build
    assert re.search(r"make\b.*ds4-server", build)
    assert ds4.checkout() == ds4.home() / "checkout"
    assert str(ds4.home()).startswith(os.environ["LOCALHARNESS_HOME"])


def test_the_pin_the_build_uses_is_the_one_the_harness_reports(monkeypatch):
    pins = (REPO / "scripts" / "versions.sh").read_text(encoding="utf-8")
    assert ds4.pinned_rev() == re.search(r'^DS4_REV="([0-9a-f]{40})"$', pins, re.M).group(1)


def test_how_long_a_launch_may_take_follows_the_models_own_size(tmp_path, monkeypatch):
    """A resident Qwen and a larger DeepSeek do not map in the same time."""
    monkeypatch.setenv(ds4.MODELS_VAR, str(tmp_path / "none-fetched"))
    qwen = ds4.start_timeout(f"ds4:{QWEN_Q2}")
    deepseek = ds4.start_timeout(f"ds4:{DSV4_Q2}")
    assert qwen == pytest.approx(ds4.START_FLOOR_S + ds4.START_S_PER_GIB * 41.73, rel=1e-3)
    assert deepseek > qwen
    cached = ds4.start_timeout(f"ds4:{DSV4_Q2},ssd_streaming=on,expert_cache=32GB")
    assert cached == pytest.approx(ds4.START_FLOOR_S + ds4.START_S_PER_GIB * 32)


# ---- each fact reaches the ds4 spelling and route (#596) -------------------------

def test_a_card_tag_makes_an_unlisted_repo_ds4s_and_its_siblings_pick_the_file(monkeypatch):
    monkeypatch.setattr(ins, "ceiling_bytes", lambda: 200 * GIB)
    repo = "someone/qwen38-ds4-mirror"
    assert screen.candidate_for("code", repo, card=QWEN_CARD) == "ds4:Qwen3.8-Flash-Next-Q4"


def test_the_store_given_is_the_one_whose_fetched_file_is_spelled(models, tmp_path, monkeypatch):
    monkeypatch.setattr(ins, "ceiling_bytes", lambda: 200 * GIB)
    conn = ms.connect(tmp_path / "other.db")
    try:
        downloads.record(conn, QWEN, downloads.GGUF, models / f"{QWEN_Q2}.gguf",
                         file=f"{QWEN_Q2}.gguf")
        assert screen.candidate_for("code", QWEN, conn=conn) == f"ds4:{QWEN_Q2}"
    finally:
        conn.close()


def test_a_ds4_spec_that_does_not_parse_is_its_own_runner_gap():
    spec = f"ds4:{QWEN_Q2},ctx=abc"
    assert screen.runner_gap("code", spec) == f"{spec}: ctx must be a positive token count"


def test_a_ds4_spec_with_no_case_for_its_method_names_the_gap(tmp_path, monkeypatch):
    import yaml
    d = tmp_path / "cases" / "svg"
    d.mkdir(parents=True)
    (d / "a.yaml").write_text(yaml.safe_dump({"id": "a", "modality": "svg", "prompt": "p",
                                              "methods": ["omnisvg"]}), encoding="utf-8")
    monkeypatch.setattr(screen, "CASES", tmp_path / "cases")
    assert screen.runner_gap("svg", f"ds4:{QWEN_Q2}") == (
        "no svg case fits the llm method (a takes omnisvg)")


def test_an_alias_never_routes_to_ds4_even_when_a_ds4_file_is_fetched(monkeypatch):
    from harness.completion import DEFAULT_GATEWAY
    monkeypatch.setattr(gguf, "fetched", lambda *a, **k: QWEN_Q2)
    assert serving.route("q3-4b").base == DEFAULT_GATEWAY
    assert serving.route(QWEN) == serving.Route(ds4.url(), QWEN_Q2, {})


def test_a_ds4_repo_the_gateway_lists_as_an_alias_stays_on_the_gateway(tmp_path, monkeypatch):
    from harness.completion import DEFAULT_GATEWAY
    monkeypatch.setattr(gguf, "fetched", lambda *a, **k: QWEN_Q2)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""\
        model_list:
          - model_name: {QWEN}
            litellm_params:
              model: openai/{QWEN_Q2}
              api_base: http://127.0.0.1:8081/v1
        """), encoding="utf-8")
    assert serving.route(QWEN, config=cfg).base == DEFAULT_GATEWAY


def test_a_ds4_repo_whose_fetched_file_ds4_does_not_list_is_not_routed_to_ds4(monkeypatch):
    monkeypatch.setattr(gguf, "fetched", lambda *a, **k: "Qwen3.8-Flash-Next-Q3_K_M")
    assert serving.route(QWEN).base != ds4.url()


def test_an_alias_fronting_ds4_on_its_own_port_names_ds4(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent(f"""\
        model_list:
          - model_name: flash
            litellm_params:
              model: openai/{QWEN_Q2}
              api_base: http://127.0.0.1:9011/v1
        """), encoding="utf-8")
    assert serving.engine_for("flash", environ={ds4.PORT_VAR: "9011"}, config=cfg) == "ds4-server"
