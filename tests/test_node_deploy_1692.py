"""A Studio deploy brings each unparked node to its sha over ssh, rolls a failed node back, and retries a down one. #1692."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

import shells
from harness import deploy, deploy_switch, node_deploy, nodes
from harness import memory_store as ms

OLD, NEW = "a" * 40, "b" * 40
FP = "Mac14,12/macOS/arm64/731b6725bbad"


def _yaml(tmp_path: Path, *entries: dict) -> Path:
    import yaml
    f = tmp_path / "nodes.yaml"
    f.write_text(yaml.safe_dump({"nodes": list(entries)}), encoding="utf-8")
    return f


def _node(name: str, **extra) -> dict:
    return {"name": name, "api_base": f"http://{name}.invalid:8083/v1", "engine": "llama-server",
            "models": ["Qwen2.5-7B-Instruct-Q4_K_M"], "machine": FP, "lanes": ["extract"], **extra}


class Fake:
    """ssh as a table: (mode, sha) -> (rc, output); every call kept with the node it went to."""

    def __init__(self, head=(0, OLD), install=None):
        self.head, self.install, self.calls = head, dict(install or {}), []

    def __call__(self, argv, script, timeout):
        assert script == node_deploy.SCRIPT and argv[0] == "ssh"
        args = shlex.split(argv[-1])[3:]
        self.calls.append((argv[-2], *args))
        if args[0] == "head":
            return self.head
        return self.install.get(args[2], (0, "reinstalled"))


@pytest.fixture
def deployed():
    """This machine's deploy of NEW finished deployed, its record written as the switch leaves it."""
    c = ms.connect()
    did = deploy._insert(c, NEW, None, Path("/releases/1-old"), OLD, time.time())
    deploy.finish(c, did, deploy.DEPLOYED, f"{NEW[:12]} serving")
    deploy_switch.save(deploy.record_path(did), {"id": did, "sha": NEW, "outcome": deploy.DEPLOYED})
    yield {"conn": c, "id": did}
    c.close()


def _follow(world, f, ssh, *, check=lambda n: "", alerts=None, retry=False):
    said = [] if alerts is None else alerts
    return node_deploy.follow(world["conn"], retry=retry, runner=ssh, check=check, alert=said.append,
                              load=lambda: nodes.load(f))


def _record(world) -> dict:
    return deploy_switch.load(deploy.record_path(world["id"]))


def test_a_node_install_runs_after_a_passing_deploy_records_its_outcome_and_skips_a_parked_node(deployed, tmp_path):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "ops@styx.invalid"}),
              _node("khryll", parked=True, deploy={"ssh": "ops@khryll.invalid"}))
    ssh = Fake()
    got = _follow(deployed, f, ssh)
    assert ssh.calls == [("ops@styx.invalid", "head", ""), ("ops@styx.invalid", "install", "", NEW, "interactive")]
    rec = _record(deployed)
    assert rec["outcome"] == deploy.DEPLOYED and set(rec["nodes"]) == {"styx"}
    assert rec["nodes"]["styx"]["outcome"] == node_deploy.DEPLOYED == got["nodes"]["styx"]["outcome"]
    assert rec["nodes"]["styx"]["previous_sha"] == OLD
    assert _follow(deployed, f, ssh)["nodes"] == {} and len(ssh.calls) == 2


def test_no_node_follows_a_deploy_that_is_running_or_did_not_pass(tmp_path):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))
    c = ms.connect()
    try:
        did = deploy._insert(c, NEW, None, Path("/releases/1-old"), OLD, time.time())
        ssh = Fake()
        assert _follow({"conn": c}, f, ssh)["deploy"] is None
        deploy.finish(c, did, deploy.ROLLED_BACK, "smoke after the switch failed")
        assert _follow({"conn": c}, f, ssh)["deploy"] is None
        assert ssh.calls == []
        deploy.finish(c, deploy._insert(c, NEW, None, Path("/releases/2-old"), OLD, time.time()), deploy.DEPLOYED, "")
        running = deploy._insert(c, "c" * 40, None, Path("/releases/3-new"), NEW, time.time())
        assert _follow({"conn": c}, f, ssh)["deploy"] is None and ssh.calls == []
        deploy.finish(c, running, deploy.ROLLED_BACK, "smoke after the switch failed")
        assert node_deploy.target(c)["sha"] == NEW, "a rolled-back deploy leaves nodes on the sha still served"
    finally:
        c.close()


def test_a_paused_deploy_queue_deploys_no_node(deployed, tmp_path):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))
    ssh = Fake()
    deploy.pause()
    try:
        assert "paused" in _follow(deployed, f, ssh)["why"] and ssh.calls == []
    finally:
        deploy.resume()


def test_a_node_already_at_the_sha_is_left_alone(deployed, tmp_path):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))
    ssh = Fake(head=(0, f"warning: something\n{NEW}\n"))
    assert _follow(deployed, f, ssh)["nodes"]["styx"]["outcome"] == node_deploy.CURRENT
    assert [c[1] for c in ssh.calls] == ["head"]


@pytest.mark.parametrize("failing", ["install", "smoke"])
def test_a_failing_node_install_rolls_the_node_back_and_alerts_and_leaves_the_studio_deployed(
        deployed, tmp_path, failing):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "styx", "key": "~/.ssh/k", "dir": "~/lh/deploy"}))
    ssh = Fake(install={NEW: (1, "FATAL: uv sync failed")} if failing == "install" else {})
    checks = iter(["nodes smoke: node styx up: sohot-extract served by fallback"] if failing == "smoke" else [])
    alerts = []
    got = _follow(deployed, f, ssh, check=lambda n: next(checks, ""), alerts=alerts)
    assert [c[1:] for c in ssh.calls] == [("head", "~/lh/deploy"), ("install", "~/lh/deploy", NEW, "interactive"),
                                          ("install", "~/lh/deploy", OLD, "interactive")]
    r = _record(deployed)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.ROLLED_BACK == got["nodes"]["styx"]["outcome"]
    assert ("uv sync failed" if failing == "install" else "served by fallback") in r["detail"]
    assert len(alerts) == 1 and "node styx" in alerts[0] and node_deploy.ROLLED_BACK in alerts[0]
    row = deployed["conn"].execute("SELECT outcome FROM deploys WHERE id = ?", (deployed["id"],)).fetchone()
    assert row["outcome"] == deploy.DEPLOYED and _record(deployed)["outcome"] == deploy.DEPLOYED
    assert _follow(deployed, f, ssh)["nodes"] == {}, "a rolled-back node waits for the next deploy"
    assert _follow(deployed, f, Fake(), retry=True)["nodes"]["styx"]["outcome"] == node_deploy.DEPLOYED


def test_a_rollback_that_fails_too_says_so(deployed, tmp_path):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))
    ssh = Fake(install={NEW: (1, "bad"), OLD: (1, "worse")})
    alerts = []
    r = _follow(deployed, f, ssh, alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.FAILED and "worse" in r["detail"] and len(alerts) == 1


def test_a_down_node_is_skipped_and_retried_at_the_next_poll(deployed, tmp_path):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))
    alerts = []
    down = Fake(head=(255, "ssh: connect to host styx port 22: Operation timed out"))
    r = _follow(deployed, f, down, alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DOWN and "timed out" in r["detail"] and alerts == []
    assert [c[1] for c in down.calls] == ["head"]
    assert node_deploy.line("styx", r).startswith("WARN")
    up = Fake()
    r = _follow(deployed, f, up, alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED and r["tries"] == 2 and alerts == []
    assert [c[1] for c in up.calls] == ["head", "install"]


def test_an_install_cut_off_by_the_network_reinstalls_next_poll_and_keeps_the_true_previous(deployed, tmp_path):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))
    r = _follow(deployed, f, Fake(install={NEW: (255, "Connection reset")}))["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DOWN and r["started"]
    # The cut install had checked NEW out already; the node is not "current", and rollback goes to OLD.
    again = Fake(head=(0, NEW), install={NEW: (1, "reinstall failed")})
    r = _follow(deployed, f, again)["nodes"]["styx"]
    assert [c[1:] for c in again.calls][1:] == [("install", "", NEW, "interactive"), ("install", "", OLD, "interactive")]
    assert r["outcome"] == node_deploy.ROLLED_BACK


def test_an_install_whose_poll_died_is_taken_up_again(deployed, tmp_path):
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))
    rec = _record(deployed)
    rec["nodes"] = {"styx": {"outcome": node_deploy.INSTALLING, "pid": 2 ** 22 + 12345, "started": True,
                             "previous_sha": OLD, "sha": NEW}}
    deploy_switch.save(deploy.record_path(deployed["id"]), rec)
    ssh = Fake(head=(0, NEW))
    assert _follow(deployed, f, ssh)["nodes"]["styx"]["outcome"] == node_deploy.DEPLOYED
    rec["nodes"]["styx"]["pid"] = os.getpid()
    deploy_switch.save(deploy.record_path(deployed["id"]), rec)
    assert _follow(deployed, f, Fake())["nodes"] == {}, "an install still running is not started twice"


def test_a_node_with_no_deploy_block_is_never_sshed_and_is_tried_again_once_configured(deployed, tmp_path):
    ssh = Fake()
    r = _follow(deployed, _yaml(tmp_path, _node("styx")), ssh)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.UNCONFIGURED and ssh.calls == []
    r = _follow(deployed, _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"})), ssh)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED


@pytest.mark.parametrize("bad, field", [({"ssh": "-oProxyJump"}, "ssh"), ({"ssh": "a b"}, "ssh"),
                                        ({"ssh": ""}, "ssh"), ({"ssh": "styx", "role": "scheduler"}, "role"),
                                        ("styx", "mapping")])
def test_a_malformed_deploy_block_names_the_field(tmp_path, bad, field):
    with pytest.raises(ValueError, match=field):
        nodes.load(_yaml(tmp_path, _node("styx", deploy=bad)))


def test_the_role_follows_lanes_and_the_ssh_line_quotes_every_argument(tmp_path):
    plain = {k: v for k, v in _node("pc").items() if k != "lanes"}
    n = nodes.load(_yaml(tmp_path, {**plain, "deploy": {"ssh": "pc", "key": "~/.ssh/k"}}))[0]
    assert n.role == "node"
    argv = node_deploy.ssh_argv(n, "install", "~/a dir; rm -rf /", NEW, n.role)
    assert argv[argv.index("-i") + 1] == str(Path("~/.ssh/k").expanduser()) and "BatchMode=yes" in argv
    assert argv[-2] == "pc" and shlex.split(argv[-1]) == ["bash", "-s", "--", "install", "~/a dir; rm -rf /", NEW, "node"]


def test_verify_checks_the_fingerprint_waits_for_the_node_then_smokes_it(tmp_path):
    n = nodes.load(_yaml(tmp_path, _node("styx")))[0]
    bare = nodes.load(_yaml(tmp_path, {**_node("styx"), "machine": ""}))[0]
    assert node_deploy.verify(bare).startswith("nodes check:")
    clock, answers = [0.0], iter([Exception("refused"), Exception("refused")])

    def get(url, node):
        got = next(answers, None)
        if got is not None:
            raise got
        return 200, {"Qwen2.5-7B-Instruct-Q4_K_M"}

    def tick(s):
        clock[0] += s
    assert node_deploy.verify(n, get=get, smoke=lambda node: [(True, "ok")], sleep=tick,
                              clock=lambda: clock[0]) == ""
    assert clock[0] == 2 * node_deploy.WARM_POLL_S
    assert "within" in node_deploy.verify(n, get=lambda u, nd: (_ for _ in ()).throw(OSError("down")),
                                          smoke=lambda node: [], sleep=tick, clock=lambda: clock[0])
    assert node_deploy.verify(n, get=get, smoke=lambda node: [(False, "served by fallback")], sleep=tick,
                              clock=lambda: clock[0]) == "nodes smoke: served by fallback"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.skipif(sys.platform == "win32", reason="the node script runs under a node's bash")
def test_the_node_script_checks_out_the_sha_syncs_and_reinstalls_in_the_checkout(tmp_path):
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    calls = tmp_path / "calls"
    uv = home / ".local" / "bin" / "uv"
    uv.write_text(f'#!/bin/sh\necho "uv $*" >> {calls}\n', encoding="utf-8")
    uv.chmod(0o755)
    repo = home / "lh" / "deploy"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "launchd.sh").write_text(f'echo "launchd $* $LH_ROLE $LH_DEPLOY" >> {calls}\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    old = _git(repo, "rev-parse", "HEAD")
    (repo / "x").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "new")
    new = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "--detach", old)
    n = nodes.load(_yaml(tmp_path, _node("styx", deploy={"ssh": "styx", "dir": "~/lh/deploy"})))[0]
    env = {**os.environ, "HOME": str(home)}

    def local(argv, script, timeout):
        got = subprocess.run([shells.resolve("bash"), *shlex.split(argv[-1])[1:]], input=script, text=True,
                             capture_output=True, env=env, timeout=timeout)
        return got.returncode, got.stdout + got.stderr
    rc, said = local(node_deploy.ssh_argv(n, "head", n.deploy_dir), node_deploy.SCRIPT, 30)
    assert rc == 0 and said.strip() == old
    (home / "lhh").mkdir()
    os.symlink(repo, home / "lhh" / "deploy")
    env["LOCALHARNESS_HOME"] = str(home / "lhh")
    rc, said = local(node_deploy.ssh_argv(n, "head", ""), node_deploy.SCRIPT, 30)
    assert rc == 0 and said.strip() == old, "no dir: means the node's own $LOCALHARNESS_HOME/deploy"
    rc, said = local(node_deploy.ssh_argv(n, "install", n.deploy_dir, new, n.role), node_deploy.SCRIPT, 30)
    assert rc == 0, said
    assert _git(repo, "rev-parse", "HEAD") == new
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "uv sync --frozen", f"launchd reinstall interactive {home}/lh/deploy"]
    rc, said = local(node_deploy.ssh_argv(n, "install", n.deploy_dir, "c" * 40, n.role), node_deploy.SCRIPT, 30)
    assert rc != 0 and _git(repo, "rev-parse", "HEAD") == new
