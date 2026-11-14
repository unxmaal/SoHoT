"""A node install runs with-gpu-lock under the project env, skips a rollback its store has outgrown, and alerts a repeated cause once. #2022."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

import shells
from harness import deploy, deploy_switch, exclusive, node_deploy, node_state, nodes, store
from harness import memory_store as ms
from test_gpu_lock_store_python_1586 import POSIX, _fake_repo, _interpreter, _run
from test_node_deploy_1692 import NEW, OLD, Fake, _follow, _git, _node, _record, _yaml, deployed  # noqa: F401 - fixture

HTTPX = "ModuleNotFoundError: No module named 'httpx'"
#: A node whose store is not copied before its install (Postgres, or the release that predates #2023).
NO_COPY = (0, "backup none: the store is Postgres")


@pytest.fixture
def sqlite_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(store.BACKEND_ENV, "sqlite")
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.setenv("LH_DEPLOY", str(tmp_path / "deploy"))
    return tmp_path


@POSIX
@pytest.mark.parametrize("repair", [True, False])
def test_with_gpu_lock_started_by_bare_python_takes_the_lease_on_a_sqlite_store(sqlite_home, repair):
    fake = _fake_repo(sqlite_home)
    _interpreter(fake / ".venv" / "bin" / "python", f'exec {sys.executable} "$@"\n')
    got = _run(fake, *(["--repair"] if repair else []), sys.executable, "-c", "print('held')")
    assert got.returncode == 0 and "Traceback" not in got.stderr, got.stderr
    assert "no gpu lease" not in got.stderr and "no batch lease" not in got.stderr, got.stderr
    assert got.stdout.strip() == "held"


@POSIX
def test_with_gpu_lock_with_no_project_env_refuses_naming_it(sqlite_home):
    got = _run(_fake_repo(sqlite_home), "true")
    assert got.returncode != 0 and "Traceback" not in got.stderr, got.stderr
    assert "httpx" in got.stderr and "uv sync" in got.stderr and sys.executable in got.stderr


@POSIX
def test_with_gpu_lock_reruns_under_the_project_venv_on_a_sqlite_store(sqlite_home):
    fake = _fake_repo(sqlite_home)
    seen = sqlite_home / "argv"
    _interpreter(fake / ".venv" / "bin" / "python", f'case "$*" in *"import httpx"*) exit 0;; esac\necho "$@" > {seen}\n')
    got = _run(fake, "--repair", "true")
    assert got.returncode == 0, got.stderr
    assert seen.read_text(encoding="utf-8").split() == ["-I", str(fake / "scripts" / "with-gpu-lock"), "--repair", "true"]


def test_on_sqlite_the_venv_is_chosen_only_when_this_interpreter_lacks_the_project(sqlite_home, monkeypatch):
    repo = sqlite_home / "repo"
    python = exclusive._venv_python(repo)
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    assert exclusive.store_python(repo, can_import=lambda p: True) is None, "this interpreter has httpx"
    monkeypatch.setitem(sys.modules, exclusive.PROJECT_MODULE, None)
    assert exclusive.store_python(repo, can_import=lambda p: True) == str(python)
    with pytest.raises(RuntimeError) as got:
        exclusive.store_python(repo, can_import=lambda p: False)
    assert str(python) in str(got.value) and "httpx" in str(got.value)


def test_the_node_state_reports_the_store_schema_without_migrating(sqlite_home):
    from harness.memory_store import migrations
    ms.connect().close()
    assert node_state.store_schema() == migrations.SCHEMA_VERSION
    got = subprocess.run([sys.executable, "-m", "harness.node_state", "schema"], capture_output=True, text=True,
                         timeout=60, cwd=Path(__file__).resolve().parents[1])
    assert got.returncode == 0 and got.stdout.splitlines()[-1] == str(migrations.SCHEMA_VERSION), got.stderr


def test_the_node_script_reports_the_release_schema_and_the_store_schema(tmp_path):
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    uv = home / ".local" / "bin" / "uv"
    uv.write_text('#!/bin/sh\ncase "$*" in *"node_state schema") echo 107;; *) exit 9;; esac\n', encoding="utf-8")
    uv.chmod(0o755)
    repo = home / "localharness" / "deploy"
    (repo / "harness" / "memory_store").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "harness" / "memory_store" / "schema.py").write_text("x = 1\nSCHEMA_VERSION = 105\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    old = _git(repo, "rev-parse", "HEAD")
    (repo / "harness" / "memory_store" / "schema.py").write_text("SCHEMA_VERSION = 107\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "new")
    n = nodes.load(_yaml(tmp_path, _node("styx", deploy={"ssh": "styx"})))[0]
    env = {k: v for k, v in os.environ.items() if k != "LOCALHARNESS_HOME"} | {"HOME": str(home)}
    argv = node_deploy.ssh_argv(n, "schema", n.deploy_dir, old)
    got = subprocess.run([shells.resolve("bash"), *shlex.split(argv[-1])[1:]], input=node_deploy.SCRIPT, text=True,
                         capture_output=True, env=env, timeout=30)
    assert got.returncode == 0 and got.stdout.splitlines() == ["code 105", "store 107"], got.stdout + got.stderr
    assert _git(repo, "rev-parse", "HEAD") != old, "reading a schema checks nothing out"


def _styx(tmp_path):
    return _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))


def test_a_rollback_to_a_release_older_than_the_node_store_is_skipped_and_says_why(shown_live, deployed, tmp_path):
    ssh, alerts = Fake(install={NEW: (1, HTTPX)}, schemas=(105, 107), copy=NO_COPY), []
    r = _follow(deployed, _styx(tmp_path), ssh, alerts=alerts)["nodes"]["styx"]
    assert ssh.sent() == [("head", ""), ("install", "", NEW, "interactive")], "no rollback install is tried"
    assert ("schema", "", OLD) in [c[1:] for c in ssh.calls]
    assert r["outcome"] == node_deploy.FAILED and r["rollback"] == "skipped"
    assert HTTPX in r["detail"] and "skipped" in r["detail"] and "schema 107" in r["detail"] and "105" in r["detail"]
    assert "no copy of it was taken" in r["detail"]
    assert len(alerts) == 1 and "NewerStore" in alerts[0]


@pytest.mark.parametrize("schemas", [(107, 107), (107, 105), None])
def test_a_rollback_is_tried_when_the_release_speaks_the_store_or_the_node_will_not_say(
        shown_live, deployed, tmp_path, schemas):
    ssh = Fake(install={NEW: (1, HTTPX)}, schemas=schemas)
    r = _follow(deployed, _styx(tmp_path), ssh)["nodes"]["styx"]
    assert ssh.sent() == [("head", ""), ("install", "", NEW, "interactive"), ("install", "", OLD, "interactive")]
    assert r["outcome"] == node_deploy.ROLLED_BACK and "rollback" not in r


def _next_deploy(world, sha: str) -> None:
    c = world["conn"]
    did = deploy._insert(c, sha, None, Path(f"/releases/{sha[:4]}"), NEW, time.time())
    deploy.finish(c, did, deploy.DEPLOYED, f"{sha[:12]} serving")
    deploy_switch.save(deploy.record_path(did), {"id": did, "sha": sha, "outcome": deploy.DEPLOYED})
    world["id"] = did


def test_consecutive_deploys_failing_the_same_way_alert_once_with_the_cause(shown_live, deployed, tmp_path):
    f, alerts = _styx(tmp_path), []
    _follow(deployed, f, Fake(install={NEW: (1, HTTPX)}), alerts=alerts)
    assert len(alerts) == 1 and HTTPX in alerts[0] and "does not alert again" in alerts[0]
    for i, sha in enumerate(("c" * 40, "d" * 40), start=2):
        _next_deploy(deployed, sha)
        r = _follow(deployed, f, Fake(install={sha: (1, HTTPX)}), alerts=alerts)["nodes"]["styx"]
        assert r["outcome"] == node_deploy.ROLLED_BACK and len(alerts) == 1, alerts
        assert f"failure {i} in a row" in r["detail"] and NEW[:12] in r["detail"]
    _next_deploy(deployed, "e" * 40)
    _follow(deployed, f, Fake(install={"e" * 40: (1, HTTPX)}, schemas=(105, 107), copy=NO_COPY), alerts=alerts)
    assert len(alerts) == 2 and "skipped" in alerts[1], "a rollback that now cannot run is a new cause"
    _next_deploy(deployed, "f" * 40)
    assert _follow(deployed, f, Fake(), alerts=alerts)["nodes"]["styx"]["outcome"] == node_deploy.DEPLOYED
    _next_deploy(deployed, "9" * 40)
    _follow(deployed, f, Fake(install={"9" * 40: (1, HTTPX)}, schemas=(105, 107), copy=NO_COPY), alerts=alerts)
    assert len(alerts) == 3 and "skipped" in alerts[2], "after a deploy that serves, the same cause alerts again"


def test_a_retried_refusal_alerts_once(shown_live, deployed, tmp_path):
    f, alerts = _styx(tmp_path), []
    for _ in range(3):
        r = _follow(deployed, f, Fake(role=""), alerts=alerts, retry=True)["nodes"]["styx"]
        assert r["outcome"] == node_deploy.REFUSED
    assert len(alerts) == 1 and "refused" in alerts[0]


def test_the_cause_leaves_out_shas_and_numbers_but_keeps_the_words():
    a = node_deploy.cause("failed", "install of efa1e7a21d77 exited rc 1: Checked 73 packages in 19ms")
    b = node_deploy.cause("failed", "install of bb30800b22f6 exited rc 1: Checked 74 packages in 3ms")
    assert a == b
    assert a != node_deploy.cause("rolled_back", "install of efa1e7a21d77 exited rc 1: Checked 73 packages in 19ms")
    assert a != node_deploy.cause("failed", "install of efa1e7a21d77 exited rc 1: uv sync failed")


def test_a_node_found_current_ends_its_failing_run(shown_live, deployed, tmp_path):
    f, alerts = _styx(tmp_path), []
    _follow(deployed, f, Fake(install={NEW: (1, HTTPX)}), alerts=alerts)
    _next_deploy(deployed, "c" * 40)
    assert _follow(deployed, f, Fake(head=(0, "c" * 40)), alerts=alerts)["nodes"]["styx"]["outcome"] == node_deploy.CURRENT
    _next_deploy(deployed, "d" * 40)
    _follow(deployed, f, Fake(install={"d" * 40: (1, HTTPX)}), alerts=alerts)
    assert len(alerts) == 2
