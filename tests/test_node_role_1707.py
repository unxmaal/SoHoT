"""A node deploy installs the role the node itself holds, refuses a guess, and fails on units beyond the role's. #1707."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import shells
from harness import deploy, deploy_switch, node_deploy
from harness import memory_store as ms
from test_node_deploy_1692 import NEW, OLD, UNITS, Fake, _follow, _node, _record, _yaml

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def world():
    c = ms.connect()
    did = deploy._insert(c, NEW, None, Path("/releases/1-old"), OLD, time.time())
    deploy.finish(c, did, deploy.DEPLOYED, f"{NEW[:12]} serving")
    deploy_switch.save(deploy.record_path(did), {"id": did, "sha": NEW, "outcome": deploy.DEPLOYED})
    yield {"conn": c, "id": did}
    c.close()


def _plain(name: str, **extra) -> dict:
    """A node with no lanes:, as styx's entry was at deploy 25."""
    return {k: v for k, v in _node(name, **extra).items() if k != "lanes"}


def test_a_node_with_no_lanes_and_no_deploy_role_installs_the_role_its_own_file_holds(world, tmp_path):
    ssh = Fake(role="interactive")
    r = _follow(world, _yaml(tmp_path, _plain("styx", deploy={"ssh": "styx"})), ssh)["nodes"]["styx"]
    assert ssh.sent() == [("head", ""), ("install", "", NEW, "interactive")]
    assert r["outcome"] == node_deploy.DEPLOYED and r["role"] == "interactive" and ssh.loaded == ["interactive"]


@pytest.mark.parametrize("held, lanes, says", [("", False, "no role file"), ("", True, "no role file"),
                                               ("node", True, "lanes:"), ("scheduler", False, "scheduler")])
def test_a_node_whose_role_is_missing_or_disagrees_is_refused_untouched(world, tmp_path, held, lanes, says):
    entry = (_node if lanes else _plain)("styx", deploy={"ssh": "styx"})
    ssh, alerts = Fake(role=held), []
    r = _follow(world, _yaml(tmp_path, entry), ssh, alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.REFUSED and says in r["detail"] and "deploy: role:" in r["detail"]
    assert ssh.sent() == [("head", "")] and ssh.role == held, "nothing is installed and the role file is left alone"
    assert len(alerts) == 1 and "refused" in alerts[0]
    assert node_deploy.line("styx", r).startswith("FAIL")
    assert _follow(world, _yaml(tmp_path, entry), ssh, alerts=alerts)["nodes"] == {}, "it waits, it does not nag"
    fixed = _yaml(tmp_path, {**entry, "deploy": {"ssh": "styx", "role": "interactive"}})
    r = _follow(world, fixed, ssh, retry=True)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED and ssh.role == "interactive"


def test_an_explicit_deploy_role_overrides_the_file_and_a_rollback_puts_the_file_back(world, tmp_path):
    f = _yaml(tmp_path, _plain("styx", deploy={"ssh": "styx", "role": "interactive"}))
    ssh = Fake(role="node", install={NEW: (1, "uv sync failed")})
    r = _follow(world, f, ssh)["nodes"]["styx"]
    assert ssh.sent() == [("head", ""), ("install", "", NEW, "interactive"), ("install", "", OLD, "node")]
    assert r["outcome"] == node_deploy.ROLLED_BACK and ssh.role == "node" and r["role"] == "node"


def test_an_install_cut_off_after_it_wrote_the_role_still_rolls_back_to_the_role_the_node_had(world, tmp_path):
    f = _yaml(tmp_path, _plain("styx", deploy={"ssh": "styx", "role": "interactive"}))
    cut = Fake(role="node", install={NEW: (255, "Connection reset")})
    assert _follow(world, f, cut)["nodes"]["styx"]["previous_role"] == "node"
    again = Fake(head=(0, NEW), role="interactive", install={NEW: (1, "reinstall failed")})
    r = _follow(world, f, again)["nodes"]["styx"]
    assert again.sent()[1:] == [("install", "", NEW, "interactive"), ("install", "", OLD, "node")]
    assert r["outcome"] == node_deploy.ROLLED_BACK and again.role == "node"


def test_extra_loaded_units_after_the_install_fail_it_and_roll_it_back(world, tmp_path):
    f = _yaml(tmp_path, _plain("styx", deploy={"ssh": "styx"}))
    ssh, alerts = Fake(role="interactive", extra=["worker", "gateway"]), []
    checked = []
    r = _follow(world, f, ssh, check=lambda n: checked.append(n.name) or "", alerts=alerts)["nodes"]["styx"]
    assert [c[1:] for c in ssh.calls] == [("head", ""), ("install", "", NEW, "interactive"), ("units", ""),
                                          ("install", "", OLD, "interactive"), ("units", "")]
    assert r["outcome"] == node_deploy.ROLLED_BACK and "extra gateway, worker" in r["detail"]
    assert checked == ["styx"], "the smoke runs once, after the rollback; the bad install never reaches it"
    assert ssh.loaded == ["interactive"] and len(alerts) == 1


@pytest.mark.parametrize("said, why", [
    ("role interactive\nwant interactive\nloaded interactive\nloaded otel", "extra otel"),
    ("role interactive\nwant interactive", "missing interactive"),
    ("role interactive\nwant interactive\ndisabled interactive", ""),
    ("role node\nwant interactive\nloaded interactive", "role file says node"),
    ("role\nwant interactive\nloaded interactive", "role file says nothing"),
    ("role interactive\nusage: launchd.sh {deploy|...}", "lists no units"),
])
def test_units_match_names_what_differs(tmp_path, said, why):
    n = node_deploy.nodes_mod.load(_yaml(tmp_path, _plain("styx", deploy={"ssh": "styx"})))[0]
    log = open(os.devnull, "w", encoding="utf-8")
    try:
        rc, got = node_deploy.units_match(n, "interactive", lambda a, s, t: (0, said), log)
    finally:
        log.close()
    assert rc == 0 and (why in got if why else got == "")


def test_a_node_at_the_sha_whose_role_the_owner_changed_is_reinstalled(world, tmp_path):
    f = _yaml(tmp_path, _plain("styx", deploy={"ssh": "styx", "role": "interactive"}))
    ssh = Fake(head=(0, NEW), role="node")
    r = _follow(world, f, ssh)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED and ssh.role == "interactive" and ssh.loaded == UNITS["interactive"]
    assert _record(world)["nodes"]["styx"]["previous_role"] == "node"


@pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")
@pytest.mark.parametrize("role, want", [("interactive", {"interactive"}), ("node", None)])
def test_launchd_units_lists_the_role_set_and_what_launchd_holds(tmp_path, role, want):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "launchctl").write_text(
        '#!/bin/bash\n'
        'if [ "$1" = print-disabled ]; then echo \'"com.unxmaal.localharness.tts" => disabled\'; exit 0; fi\n'
        'case "$2" in */com.unxmaal.localharness.interactive|*/com.unxmaal.localharness.worker) exit 0 ;; esac\n'
        'exit 113\n', encoding="utf-8")
    (bin_ / "launchctl").chmod(0o755)
    home = tmp_path / "lh"
    home.mkdir()
    (home / "role").write_text(f"{role}\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "LH_ROLE"}
    env.update(HOME=str(tmp_path), LOCALHARNESS_HOME=str(home), PATH=f"{bin_}:{env['PATH']}")
    got = subprocess.run([shells.BASH, str(REPO / "scripts" / "launchd.sh"), "units"], capture_output=True,
                         text=True, env=env, timeout=60)
    assert got.returncode == 0, got.stderr
    lines = got.stdout.splitlines()
    wanted = {ln.split()[1] for ln in lines if ln.startswith("want ")}
    if want is not None:
        assert wanted == want
    else:
        assert "worker" in wanted and "discover" not in wanted and "audit" not in wanted
    assert [ln for ln in lines if not ln.startswith("want ")] == ["loaded interactive", "disabled tts", "loaded worker"]
