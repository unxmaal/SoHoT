"""A queue deploy's switch runs its reinstall through the real machine lock, and never waits past its deadline. #1515."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from test_deploy_1506 import (BASH, _deploys, _Done, _local, _queue, _worker_runs, alerts,  # noqa: F401 - fixtures
                              posix, world)

from harness import deploy, deploy_switch, exclusive
from harness import workqueue as wq

WITH_LOCK = Path(__file__).resolve().parents[1] / "scripts" / "with-gpu-lock"
#: How long a test waits for a switch that should end on its own before it calls the switch wedged.
WEDGED_S = 90.0


def _through_the_lock(world, *, forked: bool = False) -> None:
    """The release's reinstall as production runs it: under scripts/with-gpu-lock, in a bash that forks when asked."""
    argv = f'"{sys.executable}" "{WITH_LOCK}" "{BASH}" scripts/launchd.sh'
    world["steps"].install = [BASH, "-c", f"{argv}; echo forked"] if forked else [
        sys.executable, str(WITH_LOCK), BASH, "scripts/launchd.sh"]


def _detached(path, release):
    """The switch as its own process, as spawn_switch starts it off macOS: nothing of the worker's is inherited."""
    with open(Path(path).with_suffix(".out"), "a", encoding="utf-8") as out:
        child = wq.spawn_group([sys.executable, "-I", str(Path(deploy_switch.__file__).resolve()), str(path)],
                               str(release), out, deploy._env())
    _detached.children.append(child)
    return f"pid {child.pid}"


_detached.children = []


def _outcome(path: Path, within: float) -> dict:
    end = time.monotonic() + within
    while time.monotonic() < end:
        rec = deploy_switch.load(path)
        if rec.get("outcome"):
            return rec
        time.sleep(0.2)
    pytest.fail(f"the switch wedged: still {deploy_switch.load(path).get('stage')} after {within:.0f} s")


@posix
def test_a_handed_off_deploy_reaches_deployed_through_the_real_machine_lock(world, monkeypatch):
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [])
    _through_the_lock(world)
    job = _queue(world, {"f": "two\n"})

    def popen(argv, **kw):
        return _Done(deploy.run(argv[-1], job["id"], link=world["link"], steps=world["steps"], spawn=_detached))

    ran = wq.run_pending(popen=popen, clock=lambda: _local(10))
    assert [j["id"] for j in ran] == [job["id"]] and ran[0]["handed_off"]
    rec = _outcome(deploy.record_path(_deploys()[0]["id"]), WEDGED_S)
    assert rec["outcome"] == deploy.DEPLOYED, rec.get("detail")
    wq.settle_deploys()
    assert wq.get(job["id"])["state"] == wq.DONE and _deploys()[0]["outcome"] == deploy.DEPLOYED
    rel = Path(rec["release"]).name
    assert f"reinstall {rel}" in world["log"].read_text(encoding="utf-8")
    assert not exclusive._taken(exclusive.lock_path()) and not wq.paused()


@posix
def test_a_switch_whose_reinstall_waits_on_the_machine_lock_rolls_back_and_alerts_at_its_deadline(world, monkeypatch):
    monkeypatch.setattr(deploy_switch, "SWITCH_DEADLINE_S", 3.0)
    monkeypatch.setattr(deploy_switch, "REAP_TIMEOUT_S", 5.0)
    _through_the_lock(world, forked=True)
    job = _queue(world, {"f": "two\n"})
    done = []
    with exclusive.held("video"):
        t = threading.Thread(target=lambda: done.append(_worker_runs(job, world, spawn=lambda p, r: _in(p))),
                             daemon=True)
        t.start()
        t.join(WEDGED_S)
        assert not t.is_alive(), "the switch waited on the machine lock past its deadline"
    time.sleep(2.0)
    rec = deploy_switch.load(deploy.record_path(_deploys()[0]["id"]))
    assert rec["outcome"] == deploy.ROLLED_BACK
    assert "install ran past the switch deadline of 3 s" in rec["detail"]
    assert "rollback install ran past the switch deadline" in rec["detail"]
    assert {t["site"] for t in rec["timed_out"]} == {"harness/deploy_switch.py:SWITCH_DEADLINE_S"}
    assert world["link"].resolve() == Path(rec["previous"]).resolve()
    steps = world["log"].read_text(encoding="utf-8")
    assert "reinstall" not in steps, "a killed step's child took the lock and reinstalled after the switch moved on"
    assert f"alert deploy of {job['output'][:12]} rolled_back" in steps
    assert not exclusive._taken(exclusive.lock_path())
    wq.settle_deploys()
    assert wq.get(job["id"])["state"] == wq.FAILED and _deploys()[0]["outcome"] == deploy.ROLLED_BACK


@posix
def test_a_terminated_switch_takes_its_running_step_with_it(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    rec = {"link": str(tmp_path / "deploy"), "release": str(tmp_path), "previous": str(tmp_path), "sha": "a" * 40,
           "install": [BASH, "-c", f"sleep 300 & echo $! > {pid_file}; wait"], "verify": [], "alert": ["true"],
           "rollback_install": ["true"], "log": str(tmp_path / "deploy.log"), "queue_flag": str(tmp_path / "flag")}
    path = tmp_path / "1.json"
    deploy_switch.save(path, rec)
    switch = subprocess.Popen([sys.executable, "-I", str(Path(deploy_switch.__file__).resolve()), str(path)])
    end = time.monotonic() + WEDGED_S
    while not pid_file.exists() or not pid_file.read_text(encoding="utf-8").strip():
        assert time.monotonic() < end and switch.poll() is None, "the step never started"
        time.sleep(0.1)
    grandchild = int(pid_file.read_text(encoding="utf-8"))
    switch.terminate()
    switch.wait(timeout=30)
    end = time.monotonic() + 10
    while wq.alive(grandchild) and time.monotonic() < end:
        time.sleep(0.1)
    alive = wq.alive(grandchild)
    if alive:
        os.kill(grandchild, signal.SIGKILL)
    assert not alive, "the step's own session outlived the switch that launchd stopped"


@posix
def test_a_rollback_whose_previous_release_fails_smoke_too_says_the_machine_is_broken(world, monkeypatch, tmp_path):
    broken = tmp_path / "broken"
    broken.write_text("", encoding="utf-8")
    monkeypatch.setenv("MACHINE_BROKEN", str(broken))
    job = _queue(world, {"f": "two\n"})
    _worker_runs(job, world, spawn=lambda p, r: _in(p))
    rec = deploy_switch.load(deploy.record_path(_deploys()[0]["id"]))
    assert rec["outcome"] == deploy.ROLLED_BACK and rec["environment_broken"]
    assert f"this machine is broken, not release {job['output'][:12]}" in rec["detail"]
    steps = world["log"].read_text(encoding="utf-8")
    assert f"alert this machine is broken, not the release: deploy of {job['output'][:12]}" in steps


def test_smoke_names_the_mlx_engine_when_it_is_the_upstream_that_is_down(tmp_path):
    from http.server import BaseHTTPRequestHandler

    from harness import loopback

    class NotFound(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            return None

    from tests.test_gateway_key import _smoke
    engine = loopback.ThreadingHTTPServer(("127.0.0.1", 0), NotFound)
    threading.Thread(target=engine.serve_forever, daemon=True).start()
    try:
        r = _smoke({"SOHOT_GATEWAY_KEY": "sk-right", "GATEWAY_PORT": "9", "READY_TIMEOUT": "1",
                    "MLX_PORT": str(engine.server_address[1])}, tmp_path)
    finally:
        engine.shutdown()
    assert r.returncode != 0 and "gateway not serving" in r.stdout
    assert f"the MLX engine at http://127.0.0.1:{engine.server_address[1]} answers HTTP 404" in r.stdout


def _in(path):
    deploy_switch.switch(path)
    return "inline"


@pytest.fixture(autouse=True)
def _reap():
    yield
    for child in _detached.children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
    _detached.children.clear()
