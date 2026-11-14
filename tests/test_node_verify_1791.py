"""A node deploy blames the node only for what the node does: the gateway's stale or cooled view of it is Studio-side. #1791."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from harness import deploy, deploy_switch, node_deploy, nodes
from harness import memory_store as ms
from test_node_deploy_1692 import FP, NEW, OLD, Fake, _follow, _node, _yaml

STUDIO = "Mac17,15/macOS/arm64/b82b652fe135"
MODELS = ["imajev-4b-Q8_0", "Qwen2.5-7B-Instruct-Q4_K_M"]


@pytest.fixture
def world(shown_live):
    c = ms.connect()
    did = deploy._insert(c, NEW, None, Path("/releases/1-old"), OLD, time.time())
    deploy.finish(c, did, deploy.DEPLOYED, f"{NEW[:12]} serving")
    deploy_switch.save(deploy.record_path(did), {"id": did, "sha": NEW, "outcome": deploy.DEPLOYED})
    yield {"conn": c, "id": did}
    c.close()


def _styx(tmp_path: Path) -> Path:
    """styx as nodes.yaml held it on 2026-11-10: no lanes:, two models asked by name."""
    entry = {k: v for k, v in _node("styx", models=MODELS, deploy={"ssh": "styx"}).items() if k != "lanes"}
    return _yaml(tmp_path, entry)


class Reply:
    def __init__(self, headers: dict, status: int = 200):
        self.headers, self.status_code, self.text = headers, status, ""


def _gateway(*replies: dict):
    """A smoke over the real nodes.smoke whose gateway gives each round's headers, then the last round's forever."""
    rounds = list(replies)

    def run(node):
        h = rounds.pop(0) if len(rounds) > 1 else rounds[0]
        return nodes.smoke("g", "k", [node], get=lambda url, n: (200, set(MODELS)), ask=lambda *a: Reply(h))
    return run


def _check(smoke, ask=lambda node, model: Reply({}), slept=None):
    slept = [] if slept is None else slept
    return lambda n: node_deploy.verify(n, get=lambda url, nd: (200, set(MODELS)), smoke=smoke, ask=ask,
                                        sleep=slept.append, clock=time.monotonic)


ON_NODE = {"x-sohot-node": "styx", "x-sohot-machine": FP}
FELL_BACK = {"x-sohot-fallback": "styx", "x-sohot-machine": STUDIO}


def test_a_gateway_still_naming_the_old_identity_does_not_roll_back_a_healthy_node(world, tmp_path):
    ssh, alerts = Fake(), []
    stale = {"x-sohot-node": "styx", "x-sohot-machine": "node:styx"}
    r = _follow(world, _styx(tmp_path), ssh, check=_check(_gateway(stale)), alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED, r
    assert [c[1] for c in ssh.calls] == ["head", "install", "units"], "no rollback install"
    assert len(alerts) == 1 and "restart the Studio gateway" in alerts[0]
    assert "node:styx" in alerts[0] and FP in alerts[0]


def test_the_gateway_falling_back_right_after_the_restart_passes_once_its_cooldown_ends(world, tmp_path):
    ssh, alerts, slept = Fake(), [], []
    check = _check(_gateway(FELL_BACK, ON_NODE), slept=slept)
    r = _follow(world, _styx(tmp_path), ssh, check=check, alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED and r["detail"] == f"serving {NEW[:12]} as interactive", r
    assert alerts == [] and slept and slept[-1] >= nodes.COOLDOWN_S


def test_a_fallback_line_names_both_machines_and_does_not_read_as_served():
    node =nodes.parse({"nodes": [{"name": "styx", "api_base": "http://styx.invalid:8083/v1", "engine": "llama-server",
                                   "models": MODELS, "machine": FP}]})[0]
    got = nodes.smoke("g", "k", [node], get=lambda url, n: (200, set(MODELS)), ask=lambda *a: Reply(FELL_BACK))
    assert got and all(not ok for ok, _ in got)
    for _, line in got:
        assert STUDIO in line and FP in line and "fell back" in line and "served by" not in line
        assert isinstance(line, nodes.ViaGateway)


def test_a_node_the_gateway_cannot_use_and_that_fails_directly_is_rolled_back(world, tmp_path):
    ssh, alerts = Fake(), []
    check = _check(_gateway(FELL_BACK), ask=lambda node, model: Reply({}, 500))
    r = _follow(world, _styx(tmp_path), ssh, check=check, alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.ROLLED_BACK or r["outcome"] == node_deploy.FAILED, r
    assert "HTTP 500 when asked directly" in r["detail"] and ("install", "", OLD, "interactive") in ssh.sent()


def test_a_node_that_answers_directly_but_never_through_the_gateway_stays_deployed_with_an_alert(world, tmp_path):
    ssh, alerts = Fake(), []
    r = _follow(world, _styx(tmp_path), ssh, check=_check(_gateway(FELL_BACK)), alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED and len(alerts) == 1 and STUDIO in alerts[0], (r, alerts)


class Elsewhere(Fake):
    """A node whose ssh destination is another machine than nodes.yaml names."""

    def __call__(self, argv, script, timeout):
        rc, said = super().__call__(argv, script, timeout)
        return rc, said.replace(f"machine {FP}", f"machine {STUDIO}")


def test_a_real_fingerprint_mismatch_fails_naming_both_fingerprints(shown_live, world, tmp_path):
    ssh, alerts = Elsewhere(), []
    r = _follow(world, _styx(tmp_path), ssh, check=_check(_gateway(ON_NODE)), alerts=alerts)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.FAILED, r
    assert "fingerprint mismatch" in r["detail"] and STUDIO in r["detail"] and FP in r["detail"]
    assert len(alerts) == 1 and "fingerprint mismatch" in alerts[0]


@pytest.mark.parametrize("said, strict, why", [
    (f"machine {FP}", True, ""),
    (f"machine {STUDIO}", True, "mismatch"),
    ("machine ", True, "did not report"),
    ("machine ", False, ""),
    (f"machine {STUDIO}", False, "mismatch"),
])
def test_same_machine_reads_the_fingerprint_the_node_reports(tmp_path, said, strict, why):
    node = nodes.load(_styx(tmp_path))[0]
    got = node_deploy.same_machine(node, f"role interactive\n{said}", strict=strict)
    assert (why in got) if why else got == ""
