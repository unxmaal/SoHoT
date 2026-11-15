"""A node install copies the node's store first, and a rollback past a migration puts the copy back. #2023."""
from __future__ import annotations

import json
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import shells
from harness import node_deploy, node_store_copy, nodes, store
from test_node_deploy_1692 import COPY, NEW, OLD, Fake, _follow, _git, _node, _record, _yaml, deployed  # noqa: F401 - fixture
from test_node_install_2022 import HTTPX

#: A node runs the script with `ssh ... bash -s`; on a macOS node that is /bin/bash 3.2.
BASHES = sorted({b for b in (shells.resolve("bash"), "/bin/bash") if b and Path(b).exists()})


class Migrating(Fake):
    """A node whose store the new release migrates from 105 to 107 before its install fails; a restore puts it back."""

    def __init__(self, **kw):
        super().__init__(install={NEW: (1, HTTPX)}, **kw)
        self.store = 105

    def __call__(self, argv, script, timeout):
        args = shlex.split(argv[-1])[3:]
        if args[0] == "schema":
            self.calls.append((argv[-2], *args))
            return 0, f"code 105\nstore {self.store}"
        if args[0] == "install" and args[2] == NEW:
            self.store = 107
        if args[0] == "install" and args[2:] == [OLD, "interactive", COPY]:
            self.store = 105
        return super().__call__(argv, script, timeout)


def _styx(tmp_path):
    return _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))


def test_a_failed_install_that_migrated_the_store_restores_the_copy_and_installs_the_previous_release(
        shown_live, deployed, tmp_path):
    ssh, alerts = Migrating(), []
    r = _follow(deployed, _styx(tmp_path), ssh, alerts=alerts)["nodes"]["styx"]
    assert [c[1:] for c in ssh.calls][:2] == [("head", ""), ("backup", "")], "the copy comes before the install"
    assert ssh.sent() == [("head", ""), ("install", "", NEW, "interactive"), ("install", "", OLD, "interactive", COPY)]
    assert ssh.store == 105 and r["outcome"] == node_deploy.ROLLED_BACK and r["rollback"] == "restored"
    assert (r["store_backup"], r["store_backup_schema"]) == (COPY, 105)
    assert f"put back from {COPY} (schema 105)" in r["detail"] and HTTPX in r["detail"]
    assert _record(deployed)["nodes"]["styx"]["store_backup"] == COPY
    assert len(alerts) == 1


def test_a_rollback_the_store_did_not_outgrow_leaves_the_store_as_it_is(shown_live, deployed, tmp_path):
    ssh = Fake(install={NEW: (1, HTTPX)}, schemas=(105, 105))
    r = _follow(deployed, _styx(tmp_path), ssh)["nodes"]["styx"]
    assert ssh.sent()[-1] == ("install", "", OLD, "interactive") and "rollback" not in r


def test_a_copy_newer_than_the_previous_release_is_not_put_back(shown_live, deployed, tmp_path):
    ssh = Fake(install={NEW: (1, HTTPX)}, schemas=(105, 107), copy=(0, f"backup {COPY}\nbackup_schema 106"))
    r = _follow(deployed, _styx(tmp_path), ssh)["nodes"]["styx"]
    assert ssh.sent() == [("head", ""), ("install", "", NEW, "interactive")]
    assert r["rollback"] == "skipped" and "its copy from before the install is at schema 106" in r["detail"]


def test_a_store_that_cannot_be_copied_is_not_installed_over(shown_live, deployed, tmp_path):
    ssh, alerts = Fake(copy=(1, "node store copy backup failed: OperationalError: disk I/O error")), []
    r = _follow(deployed, _styx(tmp_path), ssh, alerts=alerts)["nodes"]["styx"]
    assert ssh.sent() == [("head", "")], "nothing is installed and nothing drained"
    assert r["outcome"] == node_deploy.FAILED and "could not be copied" in r["detail"] and "disk I/O" in r["detail"]
    assert len(alerts) == 1


def test_a_node_lost_before_its_copy_is_retried(shown_live, deployed, tmp_path):
    ssh = Fake(copy=(node_deploy.SSH_DOWN, "Connection closed"))
    r = _follow(deployed, _styx(tmp_path), ssh)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DOWN and ssh.sent() == [("head", "")] and "store_backup" not in r


def test_a_retried_install_keeps_the_first_copy_until_a_release_serves(shown_live, deployed, tmp_path):
    f = _styx(tmp_path)
    dropped = Fake(install={NEW: (node_deploy.SSH_DOWN, "Connection reset")})
    assert _follow(deployed, f, dropped)["nodes"]["styx"]["outcome"] == node_deploy.DOWN
    again = Migrating()
    r = _follow(deployed, f, again)["nodes"]["styx"]
    assert "backup" not in [c[1] for c in again.calls], "a copy taken after a partial install could be migrated"
    assert r["outcome"] == node_deploy.ROLLED_BACK and r["store_backup"] == COPY
    later = Fake()
    r = _follow(deployed, f, later, retry=True)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED and "backup" in [c[1] for c in later.calls], "the rollback served"
    assert _follow(deployed, f, Fake(head=(0, NEW)), retry=True)["nodes"] == {}
    assert node_deploy.carried({"outcome": node_deploy.DEPLOYED, "store_backup": COPY}) == {}
    assert node_deploy.carried({"outcome": node_deploy.FAILED, "store_backup": COPY}) == {"store_backup": COPY}


def _store(path: Path, schema: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(schema),))
    c.commit()
    c.close()


def _schema(path: Path) -> int:
    c = sqlite3.connect(path)
    try:
        return int(c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0])
    finally:
        c.close()


def _node_home(tmp_path):
    """A node's HOME: a deploy checkout with two commits, a uv that runs python as this interpreter, a store at 105."""
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    uv = home / ".local" / "bin" / "uv"
    uv.write_text(f'#!/bin/sh\nif [ "$1" = run ]; then shift 3; exec "{sys.executable}" "$@"; fi\nexit 0\n',
                  encoding="utf-8")
    uv.chmod(0o755)
    repo = home / "localharness" / "deploy"
    (repo / "scripts").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "scripts" / "launchd.sh").write_text('echo "reinstall $LH_ROLE $1" >> "$HOME/reinstalled"\n',
                                                 encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "old")
    old = _git(repo, "rev-parse", "HEAD")
    (repo / "NEW").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "new")
    _store(home / "localharness" / "discovery.db", 105)
    return home, repo, old


def _run_script(tmp_path, home, bash, *args):
    n = nodes.load(_yaml(tmp_path, _node("styx", deploy={"ssh": "styx"})))[0]
    env = {k: v for k, v in os.environ.items() if k not in ("LOCALHARNESS_HOME", "LOCALHARNESS_STORE")}
    env["HOME"] = str(home)
    argv = node_deploy.ssh_argv(n, *args)
    return _bounded([bash, *shlex.split(argv[-1])[1:]], node_deploy.SCRIPT, env)


def _bounded(argv, script, env, timeout=60):
    """subprocess.run in its own process group, the whole group killed when TIMEOUT passes (#2038)."""
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env=env, start_new_session=True)
    try:
        out, err = p.communicate(script, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        raise
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


@pytest.mark.parametrize("bash", BASHES)
def test_the_node_script_copies_the_store_and_a_rollback_install_puts_it_back(tmp_path, bash):
    home, repo, old = _node_home(tmp_path)
    db = home / "localharness" / "discovery.db"
    got = _run_script(tmp_path, home, bash, "backup", "")
    copy = home / "localharness" / "backups" / node_store_copy.NAME
    assert got.returncode == 0 and got.stdout.splitlines() == [f"backup {copy}", "backup_schema 105"], got.stderr
    _store(db, 107)
    got = _run_script(tmp_path, home, bash, "install", "", old, "interactive", str(copy))
    assert got.returncode == 0, got.stdout + got.stderr
    assert f"restored {copy}" in got.stdout and _schema(db) == 105
    assert _git(repo, "rev-parse", "HEAD") == old
    assert (home / "reinstalled").read_text(encoding="utf-8").split() == ["reinstall", "interactive", "reinstall"]


@pytest.mark.parametrize("bash", BASHES)
def test_an_install_with_no_copy_named_leaves_the_store_alone(tmp_path, bash):
    home, repo, old = _node_home(tmp_path)
    db = home / "localharness" / "discovery.db"
    _store(db, 107)
    got = _run_script(tmp_path, home, bash, "install", "", old, "interactive")
    assert got.returncode == 0 and "restored" not in got.stdout, got.stderr
    assert _schema(db) == 107


@pytest.mark.parametrize("bash", BASHES)
def test_a_restore_from_a_missing_copy_fails_the_install_before_any_reinstall(tmp_path, bash):
    home, repo, old = _node_home(tmp_path)
    got = _run_script(tmp_path, home, bash, "install", "", old, "interactive", str(tmp_path / "gone.db"))
    assert got.returncode == 1 and "no store copy at" in got.stderr
    assert not (home / "reinstalled").exists()


def test_a_store_with_nothing_to_copy_says_so(tmp_path):
    home = tmp_path / "lh"
    assert node_store_copy.backup(home, environ={})[0].startswith("backup none: no store at")
    _store(home / "discovery.db", 105)
    (home / "store.json").write_text(json.dumps({"backend": "postgres"}), encoding="utf-8")
    assert "Postgres" in node_store_copy.backup(home, environ={})[0]
    assert "Postgres" in node_store_copy.backup(tmp_path, environ={"LOCALHARNESS_STORE": "postgres"})[0]
    (home / "store.json").unlink()
    assert node_store_copy.backup(home, environ={})[1] == "backup_schema 105"


@pytest.mark.gauntlet("an-order-the-code-needs-but-does-not-check", site="harness/node_deploy.py:<module>:import:read_text")
def test_the_node_script_carries_the_whole_copy_module():
    source = Path(node_store_copy.__file__).read_text(encoding="utf-8")
    assert "@NODE_STORE_COPY@" not in node_deploy.SCRIPT and source in node_deploy.SCRIPT
    assert "\nSOHOT_NODE_STORE_COPY\n" not in source, "the module would end the heredoc that carries it"


def test_the_copy_runs_as_a_file_with_no_package_importable(tmp_path):
    _store(tmp_path / "discovery.db", 105)
    env = {k: v for k, v in os.environ.items() if k != store.BACKEND_ENV}
    got = subprocess.run([sys.executable, "-I", "-c", Path(node_store_copy.__file__).read_text(encoding="utf-8"),
                          "backup", str(tmp_path)], capture_output=True, text=True, timeout=60, cwd=tmp_path, env=env)
    assert got.returncode == 0 and got.stdout.splitlines()[-1] == "backup_schema 105", got.stderr
    bad = subprocess.run([sys.executable, "-I", node_store_copy.__file__, "nonsense"], capture_output=True, text=True,
                         timeout=60, cwd=tmp_path)
    assert bad.returncode == 2 and "usage" in bad.stderr


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:LOCALHARNESS_STORE")
@pytest.mark.parametrize("env,marker", [(None, None), ("postgres", None), ("sqlite", "postgres"), (None, "postgres"),
                                        (" Postgres ", None), (None, "sqlite"), (None, "garbage")])
def test_the_copy_reads_the_store_backend_as_the_harness_does(tmp_path, monkeypatch, env, marker):
    home = tmp_path / "lh"
    home.mkdir()
    monkeypatch.setenv("LOCALHARNESS_HOME", str(home))
    if env is None:
        monkeypatch.delenv(store.BACKEND_ENV, raising=False)
    else:
        monkeypatch.setenv(store.BACKEND_ENV, env)
    if marker == "garbage":
        (home / store.MARKER).write_text("{not json", encoding="utf-8")
    elif marker:
        (home / store.MARKER).write_text(json.dumps({"backend": marker}), encoding="utf-8")
    assert node_store_copy._postgres(home, os.environ) == (store.backend() == store.POSTGRES)


def test_a_store_held_busy_fails_the_copy_inside_its_wait(tmp_path):
    db = tmp_path / "discovery.db"
    _store(db, 105)
    lock = sqlite3.connect(db, isolation_level=None)
    lock.execute("BEGIN EXCLUSIVE")
    code = ("import sys; from harness import node_store_copy as m; m.BUSY_WAIT_S = 0.5; "
            "raise SystemExit(m.main(sys.argv[1:]))")
    env = {k: v for k, v in os.environ.items() if k != store.BACKEND_ENV}
    env["PYTHONPATH"] = str(Path(node_store_copy.__file__).parents[1])
    try:
        started = time.monotonic()
        got = _bounded([sys.executable, "-c", code, "backup", str(tmp_path)], "", env, timeout=20)
        took = time.monotonic() - started
    finally:
        lock.close()
    assert got.returncode == 1, got.stdout + got.stderr
    assert f"{db} stayed locked for 0.5 s" in got.stderr and "TimeoutError" in got.stderr, got.stderr
    assert took < 15
