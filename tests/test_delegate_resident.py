"""Delegation goes ahead under a held lock when its model is resident and pressure is normal. #588."""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harness import delegate, mlx_server, pressure, router, serving
from harness import workqueue as wq
from harness.completion import DEFAULT_GATEWAY
from tests.test_mcp_delegate import fake  # noqa: F401


@pytest.mark.parametrize("holder, resident, level, ok", [
    ("", False, None, True),
    ("", False, 4, True),
    ("eval", True, 1, True),
    ("eval", True, None, True),
    ("eval", False, 1, False),
    ("eval", True, 2, False),
    ("eval", True, 4, False),
])
def test_admit(holder, resident, level, ok):
    got, why = delegate.admit(holder, resident, level)
    assert got is ok
    if not ok:
        assert holder in why


def test_a_refusal_says_whether_it_was_the_load_or_the_pressure():
    assert "would load" in delegate.admit("eval", False, 1)[1]
    assert "pressure is level 2" in delegate.admit("eval", True, 2)[1]


def _hold(kind="eval"):
    code = ("from harness import exclusive; import time\n"
            f"with exclusive.held({kind!r}):\n print('held', flush=True); time.sleep(30)\n")
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                             text=True, env=dict(os.environ))
    assert child.stdout.readline().strip() == "held"
    return child


@pytest.fixture
def held_by_job():
    job = wq.add(["soh", "eval", "decide"], title="decide eval")
    job.update(state=wq.RUNNING, started=time.strftime(wq._STAMP))
    wq._write(job)
    child = _hold()
    yield job
    child.kill()
    child.wait()


def _normal(monkeypatch, level=pressure.NORMAL):
    monkeypatch.setattr(pressure, "sample", lambda *a, **k: pressure.Pressure(level=level))


def test_a_resident_model_answers_while_a_job_holds_the_lock(fake, held_by_job, monkeypatch):  # noqa: F811
    _normal(monkeypatch)
    monkeypatch.setattr(delegate, "loaded", lambda where, **k: True)
    got = delegate.complete("code", "write add")
    assert got["text"] and len(fake.seen) == 1


def test_a_model_not_resident_is_refused_naming_the_job(fake, held_by_job, monkeypatch):  # noqa: F811
    _normal(monkeypatch)
    monkeypatch.setattr(delegate, "loaded", lambda where, **k: False)
    with pytest.raises(delegate.Refused, match="busy with eval") as got:
        delegate.complete("code", "write add")
    assert f"job {held_by_job['id']}" in str(got.value)
    assert "decide eval" in str(got.value) and "would load" in str(got.value)
    assert fake.seen == []


def test_a_resident_model_under_pressure_is_refused(fake, held_by_job, monkeypatch):  # noqa: F811
    _normal(monkeypatch, level=pressure.WARN)
    monkeypatch.setattr(delegate, "loaded", lambda where, **k: True)
    with pytest.raises(delegate.Refused, match="pressure is level 2"):
        delegate.complete("code", "write add")
    assert fake.seen == []


def test_decide_follows_the_same_gate(fake, held_by_job, monkeypatch):  # noqa: F811
    _normal(monkeypatch)
    monkeypatch.setattr(delegate, "loaded", lambda where, **k: False)
    schema = {"urgent": {"type": "boolean", "description": "needs action today"}}
    with pytest.raises(delegate.Refused, match=f"job {held_by_job['id']}"):
        delegate.decide("is it urgent?", schema)
    assert fake.seen == []


def test_nobody_holding_the_lock_never_asks_about_residency(fake, monkeypatch):  # noqa: F811
    def boom(where, **k):
        raise AssertionError("asked")
    monkeypatch.setattr(delegate, "loaded", boom)
    assert delegate.complete("code", "x")["text"]


def _ago(minutes):
    return time.strftime(wq._STAMP, time.localtime(time.time() - minutes * 60))


def test_the_running_job_is_named_with_an_estimate_from_earlier_runs():
    for start, end in ((100, 70), (60, 30)):
        old = wq.add(["soh", "eval"], title="decide eval")
        old.update(state=wq.DONE, started=_ago(start), finished=_ago(end), rc=0)
        wq._write(old)
    job = wq.add(["soh", "eval"], title="decide eval")
    job.update(state=wq.RUNNING, started=_ago(10))
    wq._write(job)
    got = delegate.running_job()
    assert f"job {job['id']} (decide eval)" in got
    assert "about 20 min left" in got


def test_a_running_job_with_no_history_says_so():
    job = wq.add(["soh", "eval"], title="first of its kind")
    job.update(state=wq.RUNNING, started=_ago(5))
    wq._write(job)
    assert "no earlier run to estimate from" in delegate.running_job()


def test_no_running_job_names_nothing():
    assert delegate.running_job() == ""


def _getter(table):
    def get(url):
        if url not in table:
            raise OSError(f"unreachable {url}")
        return table[url]
    return get


@pytest.mark.parametrize("status, resident", [
    ("loaded", True), ("loading", False), ("sleeping", False), ("unloaded", False)])
def test_the_router_counts_only_a_loaded_model(status, resident):
    get = _getter({router.url() + "/models": {"data": [
        {"id": "Ornith-1.5-35B-Q4_K_M", "status": {"value": status}},
        {"id": "Other", "status": {"value": "loaded" if status != "loaded" else "unloaded"}}]}})
    where = serving.Route(router.url(), "Ornith-1.5-35B-Q4_K_M", {})
    assert delegate.loaded(where, get=get) is resident


def test_mlx_counts_the_model_its_wrapper_reports_loaded():
    url = serving.MLX_URL + mlx_server.LOADED_PATH
    where = serving.Route(serving.MLX_URL, "mlx-community/Qwen3-4B-4bit", {})
    assert delegate.loaded(where, get=_getter({url: {"model": "mlx-community/Qwen3-4B-4bit"}}))
    assert not delegate.loaded(where, get=_getter({url: {"model": "mlx-community/Other"}}))
    assert not delegate.loaded(where, get=_getter({url: {"model": None}}))
    assert not delegate.loaded(where, get=_getter({}))


def test_vllm_counts_the_model_it_lists():
    where = serving.Route(serving.vllm_url(), "org/model", {})
    url = serving.vllm_url() + "/v1/models"
    assert delegate.loaded(where, get=_getter({url: {"data": [{"id": "org/model"}]}}))
    assert not delegate.loaded(where, get=_getter({url: {"data": [{"id": "org/x"}]}}))


def test_a_gateway_alias_is_resolved_to_its_upstream(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "model_list:\n"
        "  - model_name: q3-4b\n"
        "    litellm_params:\n"
        "      model: openai/mlx-community/Qwen3-4B-Instruct-2507-4bit\n"
        f"      api_base: {serving.MLX_URL}/v1\n"
        "  - model_name: eval-ornith\n"
        "    litellm_params:\n"
        "      model: openai/Ornith-1.5-35B-Q4_K_M\n"
        f"      api_base: {serving.LLAMACPP_URL}/v1\n", encoding="utf-8")
    get = _getter({
        serving.MLX_URL + mlx_server.LOADED_PATH:
            {"model": "mlx-community/Qwen3-4B-Instruct-2507-4bit"},
        router.url() + "/models":
            {"data": [{"id": "Ornith-1.5-35B-Q4_K_M", "status": {"value": "unloaded"}}]}})
    alias = serving.Route(DEFAULT_GATEWAY, "q3-4b", {})
    assert delegate.loaded(alias, get=get, config=config)
    other = serving.Route(DEFAULT_GATEWAY, "eval-ornith", {})
    assert not delegate.loaded(other, get=get, config=config)
    unknown = serving.Route(DEFAULT_GATEWAY, "nobody", {})
    assert not delegate.loaded(unknown, get=get, config=config)


def test_an_unknown_server_is_never_assumed_resident():
    where = serving.Route("http://127.0.0.1:9", "m", {})
    assert not delegate.loaded(where, get=lambda url: {"data": [{"id": "m"}]})


class _Provider:
    def __init__(self, key, default="mlx-community/Boot-4bit"):
        self.model_key = key
        self._model_map = {"default_model": default}


@pytest.mark.parametrize("key, name", [
    (None, None),
    (("mlx-community/Qwen3-4B-4bit", None, None), "mlx-community/Qwen3-4B-4bit"),
    (("default_model", None, "default_model"), "mlx-community/Boot-4bit"),
])
def test_the_mlx_wrapper_names_the_model_it_holds(key, name):
    assert mlx_server.loaded_model(_Provider(key)) == name


def test_the_mlx_wrapper_answers_the_loaded_path_and_leaves_the_rest_alone():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(404)
            self.end_headers()

    Handler.response_generator = type("G", (), {"model_provider": _Provider(
        ("mlx-community/Qwen3-4B-4bit", None, None))})()
    mlx_server.serve_loaded(Handler)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import urllib.error
    import urllib.request
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + mlx_server.LOADED_PATH, timeout=5) as r:
            assert json.loads(r.read()) == {"model": "mlx-community/Qwen3-4B-4bit"}
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/elsewhere", timeout=5)
    finally:
        srv.shutdown()
        srv.server_close()
