"""Deploy 15's rollback: the switch run as the unit runs it, an outcome whatever raises, the record kept per stage. #1610."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from harness import deploy, deploy_switch, paths, store

posix = pytest.mark.skipif(sys.platform == "win32", reason="the deploy link is a symlink, as on launchd hosts")
#: The interpreter the deploy-switch unit runs: the venv's base, so neither the venv nor its editable harness.
BASE = os.path.realpath(sys.executable)
OK = [BASE, "-c", ""]
FAIL = [BASE, "-c", "raise SystemExit(1)"]


@pytest.fixture(autouse=True)
def _sqlite_backups(monkeypatch):
    """The backups here are SQLite files, whichever store the suite runs on; the Postgres one fakes its container."""
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)


def _store(path: Path, schema: int, *, extra: bool = False) -> Path:
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT INTO meta VALUES ('schema', ?)", (str(schema),))
    if extra:
        c.execute("CREATE TABLE added_by_migration (x)")
    c.commit()
    c.close()
    return path


def _record(tmp_path: Path, *, install=FAIL, verify=None, backup: Path | None = None) -> Path:
    previous, release = tmp_path / "releases" / "13-old", tmp_path / "releases" / "15-new"
    previous.mkdir(parents=True)
    release.mkdir(parents=True)
    link = tmp_path / "deploy"
    os.symlink(previous, link)
    db = _store(tmp_path / "discovery.db", 92, extra=True)
    alerts = tmp_path / "alerts"
    rec = {"id": 15, "sha": "68928d3eb40c" + "0" * 28, "job_id": "250", "link": str(link), "release": str(release),
           "previous": str(previous), "previous_sha": "dc981b6dec9e" + "0" * 28, "db": str(db),
           "backup": str(backup or ""), "migrated": backup is not None, "queue_was_paused": False,
           "queue_flag": str(tmp_path / "paused"), "install": install, "rollback_install": OK,
           "verify": verify if verify is not None else [OK],
           "alert": [BASE, "-c", "import os, sys; open(sys.argv[1], 'a').write(os.environ['MONIT_DESCRIPTION'])",
                     str(alerts)],
           "log": str(tmp_path / "logs" / "deploy.log"), "stage": "handed_off", "outcome": ""}
    path = tmp_path / "15.json"
    deploy_switch.save(path, rec)
    return path


def _unit_env(extra: dict | None = None) -> dict:
    keep = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", store.BACKEND_ENV, "VIRTUAL_ENV")}
    return {**keep, **(extra or {})}


def _as_the_unit(path: Path, cwd: Path, env: dict) -> dict:
    got = subprocess.run(deploy.switch_argv(path), cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    rec = deploy_switch.load(path)
    assert "ModuleNotFoundError" not in got.stderr, got.stderr
    return rec


@posix
def test_the_switch_run_as_the_unit_runs_it_restores_the_store_and_rolls_back(tmp_path):
    """Release 13's switch, run as a file under -I by the base interpreter, died on `from harness import store`."""
    backup = _store(tmp_path / "discovery-15-pre92.db", 91)
    path = _record(tmp_path, backup=backup)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    rec = _as_the_unit(path, elsewhere, _unit_env())
    assert rec["outcome"] == deploy_switch.ROLLED_BACK, rec
    assert f"store restored from {backup} (schema 91)" in rec["detail"]
    c = sqlite3.connect(rec["db"])
    assert {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"meta"}
    c.close()
    assert os.path.realpath(rec["link"]) == rec["previous"]


@posix
def test_the_switch_run_as_the_unit_restores_a_postgres_store_through_its_container(tmp_path):
    """The live store is Postgres (store.json); the restore and the schema read need no psycopg in the base interpreter."""
    (paths.home() / "store.json").write_text(json.dumps({"backend": "postgres", "port": 5433}), encoding="utf-8")
    backup = tmp_path / "discovery-15-pre92.db"
    backup.write_bytes(b"PGDMP fake dump")
    bin_, calls = tmp_path / "bin", tmp_path / "docker-calls"
    bin_.mkdir()
    (bin_ / "docker").write_text(
        f'#!/bin/sh\necho "$*" >> "{calls}"\n'
        'case "$*" in\n'
        '  *pg_restore*) cat > /dev/null; echo "-- the restore script";;\n'
        '  *-tA*) echo 91;;\n'
        '  *psql*) cat > /dev/null;;\n'
        '  *) exit 9;;\n'
        'esac\n', encoding="utf-8")
    (bin_ / "docker").chmod(0o755)
    path = _record(tmp_path, backup=backup)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    rec = _as_the_unit(path, elsewhere, _unit_env({"PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}"}))
    assert rec["outcome"] == deploy_switch.ROLLED_BACK, rec
    assert f"store restored from {backup} (schema 91)" in rec["detail"]
    said = calls.read_text(encoding="utf-8").splitlines()
    assert [next(w for w in s.split() if w in ("pg_restore", "psql")) for s in said] == ["pg_restore", "psql", "psql"]


@posix
def test_a_restore_that_raises_anything_ends_failed_alerted_and_saved_with_the_new_release_kept(tmp_path, monkeypatch):
    def gone(backup, db):
        raise ModuleNotFoundError("No module named 'harness'")
    monkeypatch.setattr(deploy_switch, "restore", gone)
    path = _record(tmp_path, backup=tmp_path / "pre.db")
    rec = deploy_switch.switch(path)
    on_disk = deploy_switch.load(path)
    assert on_disk["outcome"] == deploy_switch.FAILED and on_disk["stage"] == deploy_switch.FAILED
    assert "ModuleNotFoundError: No module named 'harness'" in on_disk["detail"]
    assert os.path.realpath(rec["link"]) == rec["release"], "the store keeps the new schema, so the new release stays"
    log = Path(rec["log"]).read_text(encoding="utf-8")
    assert "rollback install" not in log
    assert "failed" in (tmp_path / "alerts").read_text(encoding="utf-8")


@posix
def test_a_rollback_that_raises_ends_failed_naming_the_exception_and_the_stage(tmp_path, monkeypatch):
    real = deploy_switch._step

    def step(rec, argv, cwd, timeout, log, what, **kw):
        if what == "rollback install":
            raise KeyError("rollback_install")
        return real(rec, argv, cwd, timeout, log, what, **kw)
    monkeypatch.setattr(deploy_switch, "_step", step)
    path = _record(tmp_path)
    deploy_switch.switch(path)
    rec = deploy_switch.load(path)
    assert rec["outcome"] == deploy_switch.FAILED
    assert "the rollback itself failed at flipped_back: KeyError" in rec["detail"]
    assert (tmp_path / "alerts").read_text(encoding="utf-8")


@posix
def test_a_forward_that_raises_anything_rolls_back_naming_it(tmp_path, monkeypatch):
    real = deploy_switch._step

    def step(rec, argv, cwd, timeout, log, what, **kw):
        if what == "install":
            raise RuntimeError("install exploded")
        return real(rec, argv, cwd, timeout, log, what, **kw)
    monkeypatch.setattr(deploy_switch, "_step", step)
    path = _record(tmp_path, install=OK)
    deploy_switch.switch(path)
    rec = deploy_switch.load(path)
    assert rec["outcome"] == deploy_switch.ROLLED_BACK
    assert rec["detail"].startswith("switch failed: RuntimeError: install exploded")
    assert os.path.realpath(rec["link"]) == rec["previous"]


@posix
def test_the_record_is_saved_after_every_stage(tmp_path, monkeypatch):
    stages, path = [], _record(tmp_path, install=OK)
    real = deploy_switch.save

    def save(path, rec):
        stages.append(rec["stage"])
        real(path, rec)
    monkeypatch.setattr(deploy_switch, "save", save)
    deploy_switch.switch(path)
    assert stages == ["switching", "flipped", "installed", "verified", deploy_switch.DEPLOYED]


@posix
def test_a_switch_killed_mid_rollback_leaves_the_stage_it_reached_not_switching(tmp_path, monkeypatch):
    real = deploy_switch._step

    def step(rec, argv, cwd, timeout, log, what, **kw):
        if what == "rollback install":
            raise SystemExit(143)
        return real(rec, argv, cwd, timeout, log, what, **kw)
    monkeypatch.setattr(deploy_switch, "_step", step)
    path = _record(tmp_path, backup=_store(tmp_path / "pre.db", 91))
    with pytest.raises(SystemExit):
        deploy_switch.switch(path)
    rec = deploy_switch.load(path)
    assert rec["stage"] == "restored" and rec["outcome"] == ""
