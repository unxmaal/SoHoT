"""A machine is a host, not a board; a run belongs to the host that served it. #697."""
import asyncio
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from evals import core
from evals import run as R
from evals.core import Case, Receipt, comparable
from evals.runners.base import BaseRunner
from harness import completion, delegate, machine, migration_check, runs
from harness import memory_store as ms
from harness import workqueue as wq

ROOT = Path(__file__).resolve().parents[1]
OS = "macOS-27.0.1-arm64-arm-64bit"
REMOTE = "http://studio-b.test:4000"
B = "Mac17,15/macOS/arm64/bbbbbbbbbbbb"


def _env(host, memory_gb=96, hw="Mac17,15"):
    return {"hw_model": hw, "os": OS, "arch": "arm64", "host": host,
            "memory_gb": memory_gb, "accelerator": {}, "versions": {}}


def test_two_hosts_with_one_board_keep_two_rows(tmp_path, machine_is):
    conn = ms.connect(tmp_path / "s.db")
    machine_is(_env("aaaaaaaaaaaa", 96))
    a = ms.remember_machine(conn)
    machine_is(_env("bbbbbbbbbbbb", 256))
    b = ms.remember_machine(conn)
    assert a != b
    got = {r["id"]: r["memory_gb"] for r in conn.execute("SELECT * FROM machines")}
    assert got == {a: 96, b: 256}
    conn.close()


def test_the_host_id_is_stable_and_hides_the_platform_uuid(tmp_path):
    one = machine.host_id(probe=lambda: "UUID-1", home=tmp_path)
    assert one == machine.host_id(probe=lambda: "UUID-1", home=tmp_path)
    assert one != machine.host_id(probe=lambda: "UUID-2", home=tmp_path)
    assert "UUID" not in one and len(one) == 12


def test_a_host_with_no_platform_uuid_persists_one(tmp_path):
    first = machine.host_id(probe=lambda: "", home=tmp_path)
    assert first and first == machine.host_id(probe=lambda: "", home=tmp_path)
    assert (tmp_path / machine.HOST_FILE).read_text(encoding="utf-8").strip() == first


def test_the_first_host_to_ask_claims_the_rows_from_before_hosts(tmp_path, machine_is):
    conn = ms.connect(tmp_path / "s.db")
    old = runs.machine_for(conn, {"hw_model": "Mac17,15", "os": OS, "arch": "arm64"})
    machine_is(_env("aaaaaaaaaaaa"))
    assert ms.machine_row(conn) == old
    assert ms.remember_machine(conn) == old
    # A receipt from before hosts still lands on the row it always did.
    assert runs.machine_for(conn, {"hw_model": "Mac17,15", "os": OS, "arch": "arm64"}) == old
    machine_is(_env("bbbbbbbbbbbb"))
    assert ms.machine_row(conn) is None
    assert ms.remember_machine(conn) != old
    conn.close()


def test_two_hosts_are_not_reported_as_one_machine(tmp_path, machine_is):
    conn = ms.connect(tmp_path / "s.db")
    for host in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
        machine_is(_env(host))
        ms.remember_machine(conn)
    assert migration_check._machines(conn) == []
    conn.close()


# --- the serving host ---------------------------------------------------------------

def _gateway_module():
    spec = importlib.util.spec_from_file_location("served_model", ROOT / "gateway" / "served_model.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_gateway_names_the_machine_that_served(monkeypatch):
    mod = _gateway_module()
    monkeypatch.setattr(mod, "this_machine", lambda: B)
    got = asyncio.run(mod.proxy_handler_instance.async_post_call_response_headers_hook(
        data={"model": "eval-7b"}, user_api_key_dict=None, response=None))
    assert got["x-sohot-machine"] == B


def test_an_upstream_on_another_host_is_not_named_as_this_machine(monkeypatch):
    mod = _gateway_module()
    monkeypatch.setattr(mod, "this_machine", lambda: B)
    monkeypatch.setattr(mod, "upstream_host", lambda model: "<host>:8080")
    got = asyncio.run(mod.proxy_handler_instance.async_post_call_response_headers_hook(
        data={"model": "eval-7b"}, user_api_key_dict=None, response=None))
    assert got["x-sohot-machine"] == "upstream:<host>:8080"


class Asks(BaseRunner):
    def __init__(self, gateway):
        self.candidate = self.spec = "sohot-code"
        self.gateway = gateway

    def generate(self, case):
        done = completion.complete_full("x", "sohot-code", gateway=self.gateway)
        return done.text, 0


@pytest.fixture
def quiet(monkeypatch, machine_is):
    for name, value in (("accelerator_id", "unified:client"), ("where_id", "host"),
                        ("swap_used_mb", 7), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(
        as_dict=lambda: {"level": 1}))
    monkeypatch.setattr(completion, "SERVED", {}, raising=False)
    machine_is(_env("aaaaaaaaaaaa"))


def _run(tmp_path, monkeypatch, gateway):
    monkeypatch.setattr(R, "build_runner", lambda candidate, gw, *a, **k: Asks(gw))
    for name in ("load_cases", "load_suite"):
        monkeypatch.setattr(core, name, lambda *a, **k: [Case("c1", "code", "x", assertions={"checks": ["True"]})])
    import argparse
    args = argparse.Namespace(
        screen=False, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
        modality="code", candidates="sohot-code", from_winners=False, gateway=gateway,
        out=str(tmp_path / "out"), split="all", max_tokens=100)
    R._execute(args)
    return json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))


def _reply(machine_header):
    headers = {"x-sohot-model": "Ornith-1.5-35B-Q4_K_M"}
    if machine_header is not None:
        headers["x-sohot-machine"] = machine_header
    return httpx.Response(200, headers=headers, json={
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})


@respx.mock
def test_a_run_through_another_hosts_gateway_is_stored_under_that_host(tmp_path, monkeypatch, quiet):
    respx.post(f"{REMOTE}/v1/chat/completions").mock(return_value=_reply(B))
    data = _run(tmp_path, monkeypatch, REMOTE)
    assert data["receipt"]["machine"] == B
    # The client's accelerator, pressure and swap describe a machine that served nothing.
    assert data["receipt"]["accelerator"] == "" and data["receipt"]["pressure"] == {}
    assert data["receipt"]["swap_used_mb"] == 0
    assert data["receipt"]["served"]["sohot-code"]["model"] == "Ornith-1.5-35B-Q4_K_M"
    conn = ms.connect()
    try:
        run = runs.newest(conn, lane="code")
        got = conn.execute("SELECT fingerprint FROM machines WHERE id = ?",
                           (run["machine_id"],)).fetchone()[0]
        assert got == B
        assert runs.client_machine_id(conn, run["id"]) == ms.machine_row(conn)
        assert run["machine_id"] not in runs.here(conn)
    finally:
        conn.close()


@respx.mock
def test_a_remote_gateway_that_does_not_say_leaves_the_run_unplaced(tmp_path, monkeypatch, quiet):
    respx.post(f"{REMOTE}/v1/chat/completions").mock(return_value=_reply(None))
    data = _run(tmp_path, monkeypatch, REMOTE)
    assert data["receipt"]["machine"].startswith("unknown")
    conn = ms.connect()
    try:
        assert runs.newest(conn, lane="code")["machine_id"] is None
    finally:
        conn.close()


@respx.mock
def test_a_local_gateway_run_stays_here(tmp_path, monkeypatch, quiet):
    local = "http://127.0.0.1:4000"
    respx.post(f"{local}/v1/chat/completions").mock(return_value=_reply(None))
    data = _run(tmp_path, monkeypatch, local)
    assert data["receipt"]["accelerator"] == "unified:client"
    conn = ms.connect()
    try:
        run = runs.newest(conn, lane="code")
        assert run["machine_id"] in runs.here(conn)
        assert data["receipt"]["machine"] == ms.this_machine()["fingerprint"]
    finally:
        conn.close()


# --- what may be ranked together ------------------------------------------------------

def _receipt(**kw):
    base = dict(modality="code", case_ids=("a",), repeat=1, sampling={}, gateway="g")
    return Receipt(**{**base, **kw})


def test_one_alias_served_at_two_contexts_is_not_one_exam():
    a = _receipt(served={"sohot-code": {"model": "m", "ctx": 8192, "slots": 1}})
    b = _receipt(served={"sohot-code": {"model": "m", "ctx": 32768, "slots": 1}})
    ok, why = comparable(a, b)
    assert not ok and "ctx" in why


def test_one_alias_resolving_to_two_models_is_not_one_exam():
    a = _receipt(served={"sohot-code": {"model": "Ornith"}})
    b = _receipt(served={"sohot-code": {"model": "Qwen"}})
    assert not comparable(a, b)[0]


def test_two_serving_hosts_are_not_one_exam():
    ok, why = comparable(_receipt(machine=B), _receipt(machine="Mac17,15/macOS/arm64/aaaaaaaaaaaa"))
    assert not ok and "machine" in why


def test_runs_from_before_serving_was_recorded_still_rank():
    assert comparable(_receipt(), _receipt(machine=B, served={"k": {"ctx": 1}}))[0]
    assert core.Receipt.from_dict(_receipt(machine=B).as_dict()).machine == B


# --- how long a job takes here --------------------------------------------------------

def _ago(minutes):
    return time.strftime(wq._STAMP, time.localtime(time.time() - minutes * 60))


def _done(title, minutes, machine_id=None):
    job = wq.add(["soh", "eval"], title=title)
    job.update(state=wq.DONE, started=_ago(minutes + 1), finished=_ago(1), rc=0)
    wq._write(job)
    if machine_id is not None:
        conn = ms.connect()
        try:
            conn.execute("UPDATE jobs SET machine_id = ? WHERE id = ?", (machine_id, int(job["id"])))
            conn.commit()
        finally:
            conn.close()


def _other_machine():
    conn = ms.connect()
    try:
        got = ms.remember_machine(conn, {"hw_model": "Mac14,12", "os": "macOS", "arch": "arm64"})
        conn.commit()
        return got
    finally:
        conn.close()


def test_durations_are_this_machines_only():
    _done("x", 10)
    _done("x", 90, _other_machine())
    assert [round(s / 60) for s in wq.durations("x")] == [10]


def test_an_estimate_from_other_machines_says_so():
    _done("slow", 60, _other_machine())
    job = wq.add(["soh", "eval"], title="slow")
    job.update(state=wq.RUNNING, started=_ago(10))
    wq._write(job)
    got = delegate.running_job()
    assert "about 50 min left" in got and "other or unrecorded machines" in got


# --- review round 2 -------------------------------------------------------------------

def test_the_gateway_names_its_machine_when_the_alias_does_not_resolve(monkeypatch):
    mod = _gateway_module()
    monkeypatch.setattr(mod, "this_machine", lambda: B)
    monkeypatch.setattr(mod.models, "resolve", lambda m: (_ for _ in ()).throw(KeyError(m)))
    got = asyncio.run(mod.proxy_handler_instance.async_post_call_response_headers_hook(
        data={"model": "eval-7b"}, user_api_key_dict=None, response=None))
    assert got == {"x-sohot-machine": B}


def test_one_loopback_list_serves_client_and_gateway():
    mod = _gateway_module()
    assert mod.LOOPBACK is machine.LOOPBACK
    assert machine.is_loopback("http://[::1]:4000") and not machine.is_loopback(REMOTE)


def test_the_gateway_names_the_context_and_slots_it_serves(monkeypatch):
    mod = _gateway_module()
    monkeypatch.setattr(mod, "this_machine", lambda: B)
    monkeypatch.setattr(mod, "served_shape", lambda model: {"ctx": 32768, "slots": 4})
    got = asyncio.run(mod.proxy_handler_instance.async_post_call_response_headers_hook(
        data={"model": "eval-7b"}, user_api_key_dict=None, response=None))
    assert got["x-sohot-ctx"] == "32768" and got["x-sohot-slots"] == "4"


@respx.mock
def test_a_remote_run_records_the_context_and_slots_the_host_served(tmp_path, monkeypatch, quiet):
    reply = _reply(B)
    reply.headers["x-sohot-ctx"] = "32768"
    reply.headers["x-sohot-slots"] = "4"
    respx.post(f"{REMOTE}/v1/chat/completions").mock(return_value=reply)
    data = _run(tmp_path, monkeypatch, REMOTE)
    assert data["receipt"]["served"]["sohot-code"] == {
        "model": "Ornith-1.5-35B-Q4_K_M", "ctx": 32768, "slots": 4}


def test_a_llamacpp_spec_takes_the_local_shape_because_llama_server_sends_no_headers(monkeypatch):
    """A llamacpp: spec goes straight to the router, whose replies carry no x-sohot-* headers. #722."""
    from harness import context, router, serving
    monkeypatch.setattr(serving, "_servable", lambda stem: stem)
    monkeypatch.setattr(R, "_served_ctx", lambda spec: 8192)
    monkeypatch.setattr(context, "served_slots", lambda spec: 2)
    seen = {(router.url().rstrip("/"), "Ornith-Q4"): {"machine": "", "machines": [], "model": "",
                                                      "ctx": None, "slots": None}}
    assert R.serving_machine(seen, B) == (B, False)
    got = R.served_shapes({"k": "llamacpp:Ornith-Q4"}, {"k": "Ornith-Q4"}, seen, False)
    assert got == {"k": {"model": "Ornith-Q4", "ctx": 8192, "slots": 2}}


def test_a_receipt_from_another_host_does_not_take_this_stores_old_row(tmp_path, machine_is):
    conn = ms.connect(tmp_path / "s.db")
    old = runs.machine_for(conn, {"hw_model": "Mac17,15", "os": OS, "arch": "arm64"})
    machine_is(_env("aaaaaaaaaaaa"))
    b = runs.machine_for(conn, _env("bbbbbbbbbbbb"))
    assert b != old
    assert ms.remember_machine(conn) == old
    conn.close()


def test_asking_for_the_client_machine_writes_nothing(tmp_path, machine_is):
    conn = ms.connect(tmp_path / "s.db")
    machine_is(_env("aaaaaaaaaaaa"))
    run_id = runs.record(conn, tmp_path / "r.json", {
        "generated": "2026-10-11T00:00:00", "environment": {**_env("bbbbbbbbbbbb"), "client": _env("cccccccccccc")},
        "receipt": {"modality": "code"}, "rows": [{"case_id": "c1", "passed": True, "candidate": "k"}]})
    client = runs.client_machine_id(conn, run_id)
    assert client is not None
    conn.execute("DELETE FROM machines WHERE id = ?", (client,))
    before = conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
    assert runs.client_machine_id(conn, run_id) is None
    assert conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0] == before
    conn.close()


def test_jobs_with_no_machine_are_not_counted_as_this_ones():
    _done("y", 20)
    _done("y", 90)
    conn = ms.connect()
    try:
        conn.execute("UPDATE jobs SET machine_id = NULL WHERE title = 'y' AND id = "
                     "(SELECT MAX(id) FROM jobs WHERE title = 'y')")
        conn.commit()
    finally:
        conn.close()
    assert [round(s / 60) for s in wq.durations("y")] == [20]
