"""The store's Docker volume (#1591): kept out of a prune, an alert when it or its container goes, a daily dump."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import cli, monitor, paths, store_service as svc

REPO = Path(__file__).resolve().parents[1]
posix = pytest.mark.skipif(sys.platform == "win32", reason="the fake docker is a sh script")


class _Docker:
    """subprocess.run for docker: inspect answers from `objects`, every call recorded."""

    def __init__(self, objects=None, rc=0, said=""):
        self.objects, self.rc, self.said, self.calls = objects or {}, rc, said, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.rc:
            return subprocess.CompletedProcess(argv, self.rc, "", self.said)
        if argv[-2] == "inspect":
            got = self.objects.get(argv[-1])
            if got is None:
                return subprocess.CompletedProcess(argv, 1, "[]\n", f"Error: No such object: {argv[-1]}")
            return subprocess.CompletedProcess(argv, 0, json.dumps([got]), "")
        return subprocess.CompletedProcess(argv, 0, "", "")


RUNNING = {"State": {"Status": "running", "Running": True, "Health": {"Status": "healthy"}}}


def _switched(home: Path) -> None:
    (home / "store.json").write_text(json.dumps({"backend": "postgres", "host": "127.0.0.1", "port": 5433}),
                                     encoding="utf-8")


# ---- the volume is kept out of compose's hands and a prune's ------------------------------------------------

def test_the_compose_file_takes_the_volume_as_external_so_compose_never_recreates_or_removes_it():
    text = svc.COMPOSE.read_text(encoding="utf-8")
    vols = text.split("\nvolumes:\n", 1)[1]
    assert f"name: {svc.VOLUME}" in vols and "external: true" in vols
    assert "labels:" not in vols, "a label here changes compose's config hash and it offers to recreate the volume"


def test_pg_up_creates_a_missing_volume_with_the_keep_label(shown_live, tmp_path):
    run = _Docker()
    assert svc.ensure_volume(run=run, home=tmp_path) == "created"
    argv = run.calls[-1][0]
    assert argv[:3] == ["docker", "volume", "create"] and argv[-1] == svc.VOLUME
    assert argv[argv.index("--label") + 1] == svc.KEEP_LABEL == "com.unxmaal.sohot.keep=true"


def test_pg_up_leaves_an_existing_volume_alone(shown_live, tmp_path):
    run = _Docker({svc.VOLUME: {"Name": svc.VOLUME, "Labels": {}}})
    assert svc.ensure_volume(run=run, home=tmp_path) == "exists"
    assert [c[0][1:3] for c in run.calls] == [["volume", "inspect"]]


def test_pg_up_on_a_switched_home_refuses_to_make_an_empty_store_where_the_lost_one_was(shown_live, tmp_path):
    _switched(tmp_path)
    run = _Docker()
    with pytest.raises(RuntimeError, match="gone and this home is switched to Postgres") as got:
        svc.ensure_volume(run=run, home=tmp_path)
    assert "pg-restore --replace" in str(got.value)
    assert all(c[0][1:3] != ["volume", "create"] for c in run.calls)


def test_compose_never_gets_a_terminal_to_ask_on(shown_live, tmp_path):
    from harness import gateway_key
    run = _Docker()
    svc.compose(["up", "-d", "--wait"], run=run, environ={}, secret=gateway_key.FileStore(tmp_path / "pw"))
    assert run.calls[0][1]["stdin"] is subprocess.DEVNULL


def test_pg_status_names_the_safe_prune_and_says_an_unlabelled_volume_is_not_covered(tmp_path):
    run = _Docker({svc.VOLUME: {"Labels": {"com.docker.compose.project": "sohot-postgres"}}, svc.CONTAINER: RUNNING})
    got = svc.guard(home=tmp_path, run=run)
    assert got["labelled"] is False and got["problems"] == [] and got["backups"] == 0
    assert f'--filter "label!={svc.KEEP_LABEL}"' in got["prune"] and "--all" in got["prune"]
    run.objects[svc.VOLUME]["Labels"]["com.unxmaal.sohot.keep"] = "true"
    assert svc.guard(home=tmp_path, run=run)["labelled"] is True


# ---- the alert when the volume or the container goes ------------------------------------------------------

def test_health_names_a_missing_volume():
    got = svc.health(run=_Docker({svc.CONTAINER: RUNNING}))
    assert len(got) == 1 and f"volume {svc.VOLUME} is gone" in got[0]


def test_health_names_a_stopped_missing_or_unhealthy_container():
    vol = {svc.VOLUME: {"Labels": {}}}
    stopped = {"State": {"Status": "exited", "Running": False}}
    sick = {"State": {"Status": "running", "Running": True, "Health": {"Status": "unhealthy"}}}
    assert "is exited" in svc.health(run=_Docker({**vol, svc.CONTAINER: stopped}))[0]
    assert "does not exist" in svc.health(run=_Docker(vol))[0]
    assert "unhealthy" in svc.health(run=_Docker({**vol, svc.CONTAINER: sick}))[0]
    assert svc.health(run=_Docker({**vol, svc.CONTAINER: RUNNING})) == []


def test_docker_not_answering_is_one_problem_not_a_crash():
    got = svc.health(run=_Docker(rc=1, said="Cannot connect to the Docker daemon at unix:///var/run/docker.sock"))
    assert len(got) == 1 and "unreachable" in got[0] and "Cannot connect" in got[0]


@posix
def test_pg_check_exits_1_on_a_missing_volume_through_a_fake_docker(tmp_path, monkeypatch, capsys):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(
        "#!/bin/sh\n"
        f'case "$*" in\n'
        f'  "volume inspect {svc.VOLUME}") echo "[]"; echo "Error response from daemon: get {svc.VOLUME}: '
        f'no such volume" >&2; exit 1;;\n'
        f'  "inspect {svc.CONTAINER}") echo \'[{json.dumps(RUNNING)}]\';;\n'
        '  *) exit 9;;\n'
        'esac\n', encoding="utf-8")
    (bin_ / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    assert cli.main(["store", "pg-check"]) == 1
    assert f"volume {svc.VOLUME} is gone" in capsys.readouterr().out
    (bin_ / "docker").write_text(
        "#!/bin/sh\n"
        f'case "$*" in\n'
        f'  "volume inspect {svc.VOLUME}") echo \'[{{"Name": "{svc.VOLUME}"}}]\';;\n'
        f'  "inspect {svc.CONTAINER}") echo \'[{json.dumps(RUNNING)}]\';;\n'
        '  *) exit 9;;\n'
        'esac\n', encoding="utf-8")
    assert cli.main(["store", "pg-check"]) == 0


def test_monit_watches_the_store_only_on_the_machine_that_hosts_it(tmp_path):
    base = {"home": str(tmp_path / "h"), "scripts": str(REPO / "scripts"), "path": "/usr/bin:/bin", "data": "/",
            "models": None, "models_floor_gib": 50, "services": []}
    assert "store_postgres" not in monitor.render({**base, "store": False})
    text = monitor.render({**base, "store": True})
    check = text.split("check program store_postgres", 1)[1].split("\n\n", 1)[0]
    assert "monit-store.sh check" in check and "monit-alert.sh store\"" in check and "recovered" in check
    backup = text.split("check program store_backup", 1)[1].split("\n\n", 1)[0]
    assert "monit-store.sh backup" in backup and "monit-alert.sh store-backup" in backup
    assert f'every "* {monitor.STORE_BACKUP_HOUR} * * *"' in backup
    assert f"timeout {svc.DUMP_TIMEOUT_S} seconds" in backup
    assert {"store", "store-backup"} <= set(monitor.KINDS)


def test_the_spec_says_the_store_is_here_only_for_a_home_switched_to_local_postgres(tmp_path):
    assert not svc.hosted_here(tmp_path)
    _switched(tmp_path)
    assert svc.hosted_here(tmp_path)
    (tmp_path / "store.json").write_text(json.dumps({"backend": "postgres", "host": "pg.example.org"}), encoding="utf-8")
    assert not svc.hosted_here(tmp_path)


def test_monits_path_reaches_docker():
    where = {"docker": "/opt/docker-bin/docker"}
    assert "/opt/docker-bin" in monitor.job_path(which=where.get).split(":")


def test_monit_runs_the_deploys_scripts_only_when_it_has_every_one_this_monitor_renders(tmp_path, monkeypatch):
    deploy = tmp_path / "deploy"
    (deploy / "scripts").mkdir(parents=True)
    monkeypatch.setattr(paths, "deploy_checkout", lambda: deploy)
    (deploy / "scripts" / "monit-alert.sh").write_text("", encoding="utf-8")
    assert monitor.scripts_dir() == paths.REPO / "scripts", "a deploy older than monit-store.sh"
    for s in (paths.REPO / "scripts").glob("monit-*.sh"):
        (deploy / "scripts" / s.name).write_text("", encoding="utf-8")
    assert monitor.scripts_dir() == deploy / "scripts"


@pytest.mark.skipif(shutil.which("monit") is None, reason="monit is not installed")
def test_the_store_checks_pass_monit_t(tmp_path):
    home = tmp_path / "h"
    s = {"home": str(home), "scripts": str(REPO / "scripts"), "path": "/usr/bin:/bin", "data": "/", "models": None,
         "models_floor_gib": 50, "services": [], "store": True}
    rc = monitor.write_rc(monitor.render(s), home)
    assert monitor.syntax(shutil.which("monit"), rc) == ""


@posix
def test_the_monit_script_runs_the_check_and_the_due_backup():
    text = (REPO / "scripts" / "monit-store.sh").read_text(encoding="utf-8")
    assert "store pg-check" in text and "store pg-backup --due" in text
    assert os.access(REPO / "scripts" / "monit-store.sh", os.X_OK)


# ---- the daily dump and its rotation ----------------------------------------------------------------------

class _Dump:
    """docker exec pg_dump writes `out`; pg_restore -l reads it and exits `toc_rc`."""

    def __init__(self, out=b"PGDMP fake custom format", toc_rc=0):
        self.out, self.toc_rc, self.calls = out, toc_rc, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if "pg_dump" in argv:
            kw["stdout"].write(self.out)
            return subprocess.CompletedProcess(argv, 0, None, b"")
        return subprocess.CompletedProcess(argv, self.toc_rc, None, b"bad toc" if self.toc_rc else b"")


def _old(home: Path, n: int, start: float) -> list[Path]:
    out = []
    for i in range(n):
        when = start + i * 86400
        p = svc.backup_dir(home) / f"{svc.BACKUP_PREFIX}{time.strftime('%Y%m%d-%H%M%S', time.localtime(when))}" \
                                   f"{svc.BACKUP_SUFFIX}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PGDMP old")
        os.utime(p, (when, when))
        out.append(p)
    return out


def test_a_backup_is_a_checked_dump_and_the_oldest_past_keep_go(tmp_path):
    start = time.mktime((2026, 11, 1, 2, 0, 0, 0, 0, -1))
    old = _old(tmp_path, 5, start)
    deploy_backup = svc.backup_dir(tmp_path) / "discovery-15-pre92.db"
    deploy_backup.write_bytes(b"a deploy's backup")
    ran = _Dump()
    got = svc.daily_dump(tmp_path, keep=3, run=ran, clock=lambda: start + 5 * 86400)
    assert not got["skipped"] and got["kept"] == 3
    assert sorted(got["removed"]) == [str(p) for p in old[:3]]
    left = svc.backups(tmp_path)
    assert left == [old[3], old[4], Path(got["path"])]
    assert Path(got["path"]).read_bytes() == b"PGDMP fake custom format"
    assert deploy_backup.exists(), "rotation touches only the daily dumps"
    assert ran.calls[0][:3] == ["docker", "exec", svc.CONTAINER] and "-Fc" in ran.calls[0]
    assert ran.calls[1] == svc.in_container(["pg_restore", "-l"], stdin=True)


def test_a_dump_that_is_not_a_custom_format_file_is_removed_and_nothing_rotates(tmp_path):
    start = time.mktime((2026, 11, 1, 2, 0, 0, 0, 0, -1))
    old = _old(tmp_path, 3, start)
    with pytest.raises(RuntimeError, match="not a pg_dump custom-format file"):
        svc.daily_dump(tmp_path, keep=1, run=_Dump(out=b""), clock=lambda: start + 9 * 86400)
    assert svc.backups(tmp_path) == old
    with pytest.raises(RuntimeError, match="pg_restore -l exited 1"):
        svc.daily_dump(tmp_path, keep=1, run=_Dump(toc_rc=1), clock=lambda: start + 9 * 86400)
    assert svc.backups(tmp_path) == old


def test_a_due_backup_skips_once_today_has_its_dump(tmp_path):
    start = time.mktime((2026, 11, 1, 2, 0, 0, 0, 0, -1))
    _old(tmp_path, 1, start)
    ran = _Dump()
    got = svc.daily_dump(tmp_path, due=True, run=ran, clock=lambda: start + 55 * 60)
    assert got["skipped"] and ran.calls == []
    tomorrow = time.mktime((2026, 11, 2, 2, 0, 0, 0, 0, -1))
    got = svc.daily_dump(tmp_path, due=True, run=ran, clock=lambda: tomorrow)
    assert not got["skipped"] and len(svc.backups(tmp_path)) == 2
    assert svc.daily_dump(tmp_path, due=True, run=ran, clock=lambda: tomorrow + 300)["skipped"]


def test_keep_below_one_is_refused(tmp_path):
    with pytest.raises(ValueError):
        svc.daily_dump(tmp_path, keep=0, run=_Dump())


def test_pg_restore_needs_a_file_and_replace(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "restore", lambda p: calls.append(p))
    assert cli.main(["store", "pg-restore"]) == 1
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    assert cli.main(["store", "pg-restore", str(dump)]) == 1 and calls == []
    assert cli.main(["store", "pg-restore", str(dump), "--replace"]) == 0 and calls == [dump]


def test_pg_backup_writes_under_this_homes_backups(monkeypatch):
    monkeypatch.setattr(svc, "dump", lambda dest, run=None: (Path(dest).parent.mkdir(parents=True, exist_ok=True),
                                                             Path(dest).write_bytes(b"PGDMP x"))[1] and dest)
    monkeypatch.setattr(svc, "verify", lambda path, run=None: None)
    assert cli.main(["store", "pg-backup", "--keep-backups", "2"]) == 0
    assert [p.parent for p in svc.backups()] == [paths.home() / "backups"]
