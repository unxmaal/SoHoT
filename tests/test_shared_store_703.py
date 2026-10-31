"""#703: one store and one gateway shared by several machines: job claims, leases, gateway switches."""
import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from harness import adopt, completion, exclusive, gateway, gateway_switch as gs
from harness import memory_store as ms
from harness import reasons
from harness import workqueue as wq
from tests import conftest

REPO = Path(__file__).resolve().parent.parent
OTHER = {"hw_model": "Other1,1", "os": "Linux", "arch": "x86_64", "host": "b-host"}


@pytest.fixture(autouse=True)
def _no_marker(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)


def _as_other_machine(monkeypatch):
    """This process now answers as a second machine sharing the store."""
    from harness import machine
    facts = {**OTHER, "fingerprint": machine.fingerprint(*OTHER.values())}
    conftest.stand_in_machine(monkeypatch, facts)
    conn = ms.connect()
    try:
        got = ms.remember_machine(conn, facts)
        conn.commit()
        return got
    finally:
        conn.close()


def _unowned(job):
    conn = ms.connect()
    try:
        conn.execute("UPDATE jobs SET machine_id = NULL WHERE id = ?", (int(job["id"]),))
        conn.commit()
    finally:
        conn.close()


def test_two_workers_on_one_store_run_an_unowned_job_once(tmp_path, monkeypatch):
    marks = tmp_path / "ran"
    job = wq.add([sys.executable, "-c", f"open({str(marks)!r}, 'a').write('x')"])
    _unowned(job)
    seen_by_a = wq.pending()[0]
    # Its own patcher: undoing the shared one dropped the autouse home and opened the live store. #804.
    with pytest.MonkeyPatch.context() as other:
        _as_other_machine(other)
        seen_by_b = wq.pending()[0]
        assert seen_by_a["id"] == seen_by_b["id"]
        wq.run_one(seen_by_b)
    wq.run_one(seen_by_a)
    assert marks.read_text(encoding="utf-8") == "x"


def test_a_claimed_job_is_stamped_with_the_machine_that_runs_it(tmp_path, monkeypatch):
    job = wq.add([sys.executable, "-c", "pass"])
    _unowned(job)
    b = _as_other_machine(monkeypatch)
    wq.run_one(wq.pending()[0])
    assert wq.get(job["id"])["machine_id"] == b


def test_recover_on_one_machine_leaves_another_machines_stamped_running_job(monkeypatch):
    # A regression guard, green before #703 too; the red case is the unowned job below.
    job = wq.add([sys.executable, "-c", "pass"])
    conn = ms.connect()
    try:
        here = ms.machine_row(conn)
        conn.execute("UPDATE jobs SET state = ?, machine_id = ? WHERE id = ?",
                     (wq.RUNNING, here, int(job["id"])))
        conn.commit()
    finally:
        conn.close()
    _as_other_machine(monkeypatch)
    wq.run_pending()
    assert wq.get(job["id"])["state"] == wq.RUNNING


def test_recover_does_not_fail_an_unowned_running_job(monkeypatch):
    job = wq.add([sys.executable, "-c", "pass"])
    _unowned(job)
    conn = ms.connect()
    try:
        conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.RUNNING, int(job["id"])))
        conn.commit()
    finally:
        conn.close()
    _as_other_machine(monkeypatch)
    wq.run_pending()
    assert wq.get(job["id"])["state"] == wq.RUNNING


def test_a_machine_with_no_machines_row_recovers_nothing(monkeypatch):
    job = wq.add([sys.executable, "-c", "pass"])
    _unowned(job)
    conn = ms.connect()
    try:
        conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.RUNNING, int(job["id"])))
        conn.commit()
    finally:
        conn.close()
    conftest.stand_in_machine(monkeypatch, {**OTHER, "host": "new-host"})
    wq._recover()
    assert wq.current() is None
    assert wq.get(job["id"])["state"] == wq.RUNNING


def test_recover_still_fails_this_machines_own_interrupted_job():
    job = wq.add([sys.executable, "-c", "pass"])
    job["state"] = wq.RUNNING
    wq._write(job)
    wq.run_pending()
    got = wq.get(job["id"])
    assert got["state"] == wq.FAILED and "interrupted" in got["note"]


# ---- the store lease ------------------------------------------------------------------

def test_a_lease_held_by_another_machine_is_refused_until_it_expires():
    from harness import lease
    conn = ms.connect()
    try:
        assert lease.take(conn, "discover", {"machine_id": 1, "pid": 10}, 100, now=0) == {}
        got = lease.take(conn, "discover", {"machine_id": 2, "pid": 20}, 100, now=50)
        assert got["machine_id"] == 1
        assert lease.take(conn, "discover", {"machine_id": 2, "pid": 20}, 100, now=101) == {}
        assert lease.holder(conn, "discover")["machine_id"] == 2
    finally:
        conn.close()


def test_a_lease_left_by_a_dead_process_on_the_same_machine_is_taken_over():
    from harness import lease
    conn = ms.connect()
    try:
        lease.take(conn, "discover", {"machine_id": 1, "pid": 10}, 100, now=0)
        assert lease.take(conn, "discover", {"machine_id": 1, "pid": 11}, 100, now=5,
                          alive=lambda pid: True)["pid"] == 10
        assert lease.take(conn, "discover", {"machine_id": 1, "pid": 11}, 100, now=5,
                          alive=lambda pid: False) == {}
    finally:
        conn.close()


def test_release_removes_only_the_owners_lease():
    from harness import lease
    conn = ms.connect()
    try:
        lease.take(conn, "discover", {"machine_id": 1, "pid": 10}, 100, now=0)
        assert not lease.release(conn, "discover", {"machine_id": 2, "pid": 10})
        assert lease.release(conn, "discover", {"machine_id": 1, "pid": 10})
        assert lease.holder(conn, "discover") == {}
    finally:
        conn.close()


def test_a_second_discover_loop_with_the_lease_held_refuses_to_start(monkeypatch, capsys):
    import argparse
    from harness import lease
    from harness.commands import loop as loop_cmd
    conn = ms.connect()
    try:
        lease.take(conn, loop_cmd.LEASE, {"machine_id": 999, "pid": 1}, 3600)
    finally:
        conn.close()
    steps = []
    monkeypatch.setattr(loop_cmd.discover_cmd, "cmd_discover", lambda a: steps.append(a) or 0)
    rc = loop_cmd._run_loop(argparse.Namespace(run=True, lane=""))
    assert rc != 0 and steps == []
    assert "lease" in capsys.readouterr().err


def test_a_dry_run_loop_does_not_need_the_lease(monkeypatch):
    import argparse
    from harness import lease
    from harness.commands import loop as loop_cmd
    conn = ms.connect()
    try:
        lease.take(conn, loop_cmd.LEASE, {"machine_id": 999, "pid": 1}, 3600)
    finally:
        conn.close()
    ran = []
    monkeypatch.setattr(loop_cmd, "_run_loop_held", lambda a, keep=None: ran.append(a) or 0)
    assert loop_cmd._run_loop(argparse.Namespace(run=False, lane="")) == 0 and ran


def test_renew_extends_only_the_holders_lease():
    from harness import lease
    conn = ms.connect()
    try:
        me, other = {"machine_id": 1, "pid": 10}, {"machine_id": 2, "pid": 20}
        lease.take(conn, "discover", me, 100, now=0)
        assert lease.renew(conn, "discover", me, 100, now=90)
        assert lease.holder(conn, "discover")["expires"] == 190
        assert not lease.renew(conn, "discover", other, 100, now=95)
        assert lease.take(conn, "discover", other, 100, now=150)["machine_id"] == 1
    finally:
        conn.close()


def test_a_loop_that_lost_its_lease_stops_before_the_next_step(monkeypatch, capsys):
    import argparse
    from harness import lease
    from harness.commands import loop as loop_cmd
    steps = []

    def step(a):
        steps.append(a)
        conn = ms.connect()
        try:
            conn.execute("UPDATE meta SET value = ? WHERE key = ?",
                         ('{"machine_id": 999, "pid": 1, "expires": 1e12}',
                          lease.PREFIX + loop_cmd.LEASE))
            conn.commit()
        finally:
            conn.close()
        return 0

    monkeypatch.setattr(loop_cmd.discover_cmd, "cmd_discover", step)
    rc = loop_cmd._run_loop(argparse.Namespace(run=True, lane=""))
    assert rc != 0 and len(steps) == 1
    assert "lease" in capsys.readouterr().err


# ---- periodic units on one designated machine -----------------------------------------

@pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")
def test_a_serving_node_generates_no_periodic_units(tmp_path):
    from tests import shells
    env = {**os.environ, "LH_ROLE": "node"}
    proc = subprocess.run([shells.BASH, str(REPO / "scripts" / "launchd.sh"), "generate",
                           str(tmp_path)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    names = {p.name for p in tmp_path.glob("*.plist")}
    assert not any(".discover." in n or ".audit." in n for n in names), names
    assert any(".worker." in n for n in names)


@pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")
def test_the_role_is_remembered_so_a_plain_reinstall_keeps_it(tmp_path):
    from tests import shells
    env = {k: v for k, v in os.environ.items() if k != "LH_ROLE"}
    env["LOCALHARNESS_HOME"] = str(tmp_path / "home")

    def generate(out, **extra):
        proc = subprocess.run([shells.BASH, str(REPO / "scripts" / "launchd.sh"), "generate",
                               str(out)], capture_output=True, text=True, env={**env, **extra})
        assert proc.returncode == 0, proc.stderr
        return {p.name for p in out.glob("*.plist")}

    assert any(".discover." in n for n in generate(tmp_path / "first"))
    generate(tmp_path / "node", LH_ROLE="node")
    names = generate(tmp_path / "again")
    assert not any(".discover." in n or ".audit." in n for n in names), names


@pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")
def test_an_unknown_role_is_refused(tmp_path):
    from tests import shells
    env = {**os.environ, "LH_ROLE": "nodee"}
    proc = subprocess.run([shells.BASH, str(REPO / "scripts" / "launchd.sh"), "generate",
                           str(tmp_path)], capture_output=True, text=True, env=env)
    assert proc.returncode != 0 and "LH_ROLE" in proc.stderr


# ---- the gateway switch drains rather than cuts a request off ------------------------

class Busy:
    """A gateway with one request in flight until `until`, on a clock that moves only by sleep."""

    def __init__(self, until):
        self.t = 0.0
        self.until = until

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def in_flight(self, base):
        return 1 if self.t < self.until else 0


def test_a_long_remote_request_is_not_cut_off_by_the_switch(monkeypatch):
    longest = completion.timeout_for(completion.budget("code"))
    clock = Busy(until=longest)
    monkeypatch.setattr(gs, "in_flight", clock.in_flight)
    restarts = []
    got = gs.wait_then_restart("http://gw", lambda: restarts.append(clock.now()),
                               poll_s=1, clock=clock.now, sleep=clock.sleep)
    assert restarts and restarts[0] >= longest, (restarts, longest)
    assert got["how"] in ("idle", "drained")


def test_the_drain_outlasts_every_request_the_ladder_allows():
    longest = max(completion.timeout_for(b) for rungs in completion.LADDER.values() for b in rungs)
    assert gs.MAX_WAIT_S + gs.DRAIN_S > longest
    assert gs.DRAIN_S > longest


def test_while_draining_the_gateway_refuses_new_requests_and_says_why(monkeypatch):
    clock = Busy(until=10_000)
    monkeypatch.setattr(gs, "in_flight", clock.in_flight)
    seen = []
    gs.wait_then_restart("http://gw", lambda: seen.append(gs.draining()), idle_s=1,
                         max_wait_s=5, drain_s=10, poll_s=1, clock=clock.now, sleep=clock.sleep)
    assert seen and seen[0]
    assert not gs.draining()


def test_a_drain_flag_left_by_a_dead_switch_expires():
    gs.start_drain(until=100.0)
    assert gs.draining(now=99.0)
    assert not gs.draining(now=101.0)


def test_the_gateway_hook_refuses_a_request_while_draining():
    spec = importlib.util.spec_from_file_location("served_model_703",
                                                  REPO / "gateway" / "served_model.py")
    served = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(served)
    hook = served.proxy_handler_instance.async_pre_call_hook
    data = {"model": "sohot-code"}
    assert asyncio.run(hook(None, None, dict(data), "acompletion"))["model"] == "sohot-code"
    gs.start_drain()
    with pytest.raises(Exception) as got:
        asyncio.run(hook(None, None, dict(data), "acompletion"))
    assert getattr(got.value, "status_code", None) == 503
    assert "draining" in str(getattr(got.value, "detail", got.value))


@respx.mock
def test_a_request_refused_by_a_draining_gateway_is_charged_to_the_harness():
    gw = "http://127.0.0.1:4000"
    respx.post(f"{gw}/v1/chat/completions").mock(return_value=httpx.Response(
        503, json={"error": {"message": "the gateway is draining for an alias switch; retry once it has restarted", "code": "503"}}))
    with pytest.raises(completion.CompletionError) as got:
        completion.complete("hi", model="sohot-code", gateway=gw)
    cls = got.value.failure_class or reasons.classify(str(got.value))
    assert cls == reasons.REFUSED_BY_GATEWAY
    assert reasons.classify(str(got.value)) == reasons.REFUSED_BY_GATEWAY
    assert reasons.CLASSES[cls][1] == reasons.HARNESS


# ---- a platform with no restart method fails loudly ----------------------------------

CONFIG = {"model_list": [
    {"model_name": "q3-4b", "litellm_params": {
        "model": "openai/mlx-community/Qwen3-4B-Instruct-2507-4bit",
        "api_base": "http://127.0.0.1:8081/v1", "api_key": "not-needed"}},
    {"model_name": "local-large", "litellm_params": {
        "model": "openai/mlx-community/Qwen2.5-7B-Instruct-4bit",
        "api_base": "http://127.0.0.1:8081/v1", "api_key": "not-needed"}},
]}


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    monkeypatch.setenv(gateway.ENV_VAR, str(path))
    monkeypatch.delenv("LLAMACPP_PORT", raising=False)
    gateway.write_served(path)
    conn = ms.connect()
    try:
        adopt.record(conn, adopt.Verdict("code", "q3-4b", "local-large", True, "won",
                                         adopt.BY_HAND))
    finally:
        conn.close()
    return path


def test_restart_service_on_linux_does_not_claim_success(monkeypatch):
    monkeypatch.setattr(gs.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="no restart method on linux"):
        gs.restart_service()


def test_an_adoption_on_linux_records_a_failed_switch_with_the_reason(config, monkeypatch):
    monkeypatch.setattr(gs.sys, "platform", "linux")
    spawned = []
    gs.spawn(requested_at=7.0, popen=lambda *a, **k: spawned.append(a))
    assert spawned == []
    conn = ms.connect()
    try:
        failed = gs.failures(conn)
    finally:
        conn.close()
    assert [f["lane"] for f in failed] == ["code"]
    assert "no restart method on linux" in failed[0]["reason"]
    # old_spec comes from _old_spec in _record on both platforms: what the alias served.
    assert failed[0]["old_spec"] == CONFIG["model_list"][0]["litellm_params"]["model"]
