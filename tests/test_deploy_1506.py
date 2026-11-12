"""A deploy is a queue job: queued per green main commit, built alongside, switched, verified or rolled back. #1506."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import shells
from harness import deploy, deploy_switch, paths
from harness import memory_store as ms
from harness import workqueue as wq

BASH = shells.resolve("bash")
posix = pytest.mark.skipif(sys.platform == "win32" or BASH is None,
                           reason="releases are git checkouts behind a symlink and bash scripts, as on launchd hosts")
NOOP = [sys.executable, "-c", ""]

SMOKE = """#!/bin/bash
# Fails everywhere with fail-smoke, and only on the live release with fail-smoke-live.
[ -f fail-smoke ] && exit 1
if [ -f fail-smoke-live ] && [ "$(cd "$DEPLOY_LINK" && pwd -P)" = "$(pwd -P)" ]; then exit 1; fi
if [ -f "${MACHINE_BROKEN:-/nonexistent}" ] && [ "$(cd "$DEPLOY_LINK" && pwd -P)" = "$(pwd -P)" ]; then exit 1; fi
echo "smoke $(basename "$(pwd -P)")${SMOKE_PHASE:+ $SMOKE_PHASE}" >> "$DEPLOY_LOG"
"""
INSTALL = 'echo "reinstall $(basename "$(pwd -P)")" >> "$DEPLOY_LOG"\n'
ALERT = 'echo "alert $MONIT_DESCRIPTION" >> "$DEPLOY_LOG"\n'
REPAIR = 'echo "repair $(basename "$(pwd -P)")" >> "$DEPLOY_LOG"\n'
MIGRATE = """import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute("CREATE TABLE planted_by_migration (x)")
c.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (sys.argv[2],))
c.commit()
"""


@pytest.fixture(autouse=True)
def alerts(monkeypatch):
    """Alerts the worker's settle raises, kept here instead of on this machine's desktop."""
    said = []
    monkeypatch.setattr(deploy, "_alert_here", said.append)
    return said


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(work: Path, files: dict, msg: str) -> str:
    for rel, text in files.items():
        p = work / rel
        if text is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", msg)
    _git(work, "push", "-q", "origin", "HEAD:main")
    return _git(work, "rev-parse", "HEAD")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """An origin with one release-shaped commit, and the live home's deploy as a plain clone of it."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "t")
    first = _commit(work, {"scripts/smoke.sh": SMOKE, "scripts/launchd.sh": INSTALL, "scripts/monit-alert.sh": ALERT,
                           "scripts/gguf-aux.sh": REPAIR,
                           "migrate.py": MIGRATE, ".gitignore": "evals/cases/stt/\n.venv/\n",
                           "harness/memory_store/schema.py": f"SCHEMA_VERSION = {ms.SCHEMA_VERSION}\n"}, "first")
    link = paths.home() / "deploy"
    subprocess.run(["git", "clone", "-q", str(origin), str(link)], check=True)
    (link / "evals" / "cases" / "stt").mkdir(parents=True)
    (link / "evals" / "cases" / "stt" / "clip.yaml").write_text("imported\n", encoding="utf-8")
    (link / ".venv").mkdir()
    (link / ".venv" / "big").write_text("venv\n", encoding="utf-8")
    log = tmp_path / "deploy-steps.log"
    monkeypatch.setenv("DEPLOY_LINK", str(link))
    monkeypatch.setenv("DEPLOY_LOG", str(log))
    hf = tmp_path / "hf"
    hf.mkdir()
    monkeypatch.setenv("HF_HOME", str(hf))
    (paths.home() / deploy_switch.INSTALL_ENV).write_text(f"HF_HOME={hf}\n", encoding="utf-8")
    ms.connect().close()
    steps = deploy.Steps(sync=NOOP, probe=NOOP, smoke=[BASH, "scripts/smoke.sh"],
                         migrate=[sys.executable, "migrate.py", str(ms.db_path()), str(ms.SCHEMA_VERSION + 1)],
                         coherence=NOOP, install=[BASH, "scripts/launchd.sh"], alert=[BASH, "scripts/monit-alert.sh"],
                         repair=[BASH, "scripts/gguf-aux.sh"])
    return {"origin": origin, "work": work, "link": link, "first": first, "log": log, "steps": steps, "hf": hf}


def _green(sha):
    return True, f"check-macos passed for {sha[:12]}"


def _inline(path, release):
    deploy_switch.switch(path)
    return "inline"


class _Done:
    def __init__(self, rc):
        self.returncode = rc


def _worker_runs(job, w, spawn=_inline):
    """What the worker does with a claimed deploy job: run its command, here in process."""
    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        return _Done(deploy.run(argv[-1], job["id"], link=w["link"], steps=w["steps"], spawn=spawn))
    return wq.run_one(job, popen=popen)


def _schema() -> int:
    c = sqlite3.connect(ms.db_path())
    try:
        return int(c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0])
    finally:
        c.close()


def _tables() -> set:
    c = sqlite3.connect(ms.db_path())
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def _deploys() -> list[dict]:
    with wq._store() as c:
        return deploy.recent(c)


def _local(hour: int, minute: int = 0) -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hour, minute, 0, 0, 0, -1))


# --- enqueue -----------------------------------------------------------------------------------------------------


@posix
def test_a_green_sha_queues_exactly_one_deploy_job_and_a_repoll_queues_none(world):
    head = _commit(world["work"], {"f": "two\n"}, "two")
    got = deploy.poll(src=world["link"], green=_green, environ={})
    assert got["queued"]["kind"] == deploy.KIND and got["queued"]["output"] == head
    assert got["queued"]["argv"][-3:] == ["deploy", "run", head]
    again = deploy.poll(src=world["link"], green=_green, environ={})
    assert again["queued"] is None and "already queued" in again["why"]
    assert [j["output"] for j in wq.jobs() if j["kind"] == deploy.KIND] == [head]


@posix
def test_a_newer_green_sha_supersedes_the_pending_deploy_job(world):
    older = _commit(world["work"], {"f": "two\n"}, "two")
    first = deploy.poll(src=world["link"], green=_green, environ={})["queued"]
    newer = _commit(world["work"], {"f": "three\n"}, "three")
    got = deploy.poll(src=world["link"], green=_green, environ={})
    assert got["queued"]["output"] == newer and got["superseded"] == [first["id"]]
    states = {j["output"]: j["state"] for j in wq.jobs() if j["kind"] == deploy.KIND}
    assert states == {older: wq.CANCELLED, newer: wq.PENDING}


@posix
def test_a_red_or_unfinished_sha_and_the_deployed_head_queue_nothing(world):
    assert deploy.poll(src=world["link"], green=_green, environ={})["why"].endswith("already deployed")
    _commit(world["work"], {"f": "two\n"}, "two")
    got = deploy.poll(src=world["link"], green=lambda sha: (False, "check-macos did not pass"), environ={})
    assert got["queued"] is None and got["why"] == "check-macos did not pass"
    assert not [j for j in wq.jobs() if j["kind"] == deploy.KIND]


@posix
def test_paused_deploys_queue_nothing_until_resumed(world):
    _commit(world["work"], {"f": "two\n"}, "two")
    deploy.pause()
    assert deploy.poll(src=world["link"], green=_green, environ={})["queued"] is None
    assert "paused" in deploy.blocked()
    deploy.resume()
    assert deploy.poll(src=world["link"], green=_green, environ={})["queued"] is not None


# --- gates -------------------------------------------------------------------------------------------------------


def _pending_deploy() -> dict:
    return wq.add(["true"], title="deploy x", kind=deploy.KIND, output="x" * 40, priority=deploy.PRIORITY,
                  cwd=str(paths.home()))


@pytest.mark.parametrize("hour,minute", [(10, 0), (19, 59), (20, 30), (23, 0), (3, 0), (7, 59)])
def test_a_deploy_job_is_ready_at_any_hour_since_the_day_window_went(monkeypatch, hour, minute):
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [])
    job = _pending_deploy()
    other = wq.add(["true"], title="measure", cwd=str(paths.home()))
    ids = [j["id"] for j in wq.ready(now=_local(hour, minute))]
    assert job["id"] in ids and other["id"] in ids and not hasattr(deploy, "in_window")


def test_a_deploy_job_waits_while_a_sweep_runs(monkeypatch):
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [
        {"what": "discover loop", "pid": 4242, "started": None, "commit": "", "command": "discover --loop"}])
    job = _pending_deploy()
    assert job["id"] not in [j["id"] for j in wq.ready(now=_local(10))]
    assert "discover loop (pid 4242" in deploy.blocked()


def test_a_ready_deploy_never_interrupts_a_running_job_and_runs_before_the_rest(monkeypatch):
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [])
    monkeypatch.setattr(time, "time", lambda: _local(10))
    measure = wq.add(["true"], title="measure", cwd=str(paths.home()))
    job = _pending_deploy()
    assert wq.needs(job) == wq.DEPLOY
    assert wq.needs(measure) == wq.GPU
    # A cloud job running leaves the GPU free, yet nothing starts while a ready deploy waits for it.
    assert wq._startable({object(): (wq.CLOUD, "0099")}, _local(10)) is None
    assert wq._startable({object(): (wq.GPU, "0099")}, _local(10)) is None
    first, cls = wq._startable({}, _local(10))
    assert (first["id"], cls) == (job["id"], wq.DEPLOY)
    assert not wq._free(wq.CLOUD, {object(): (wq.DEPLOY, job["id"])})
    assert measure["id"] != first["id"]


# --- build, switch, verify, roll back ------------------------------------------------------------------------------


def _queue(world, files: dict) -> dict:
    head = _commit(world["work"], files, "next")
    job = deploy.poll(src=world["link"], green=_green, environ={})["queued"]
    assert job["output"] == head
    return job


def _claim(job) -> dict:
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    return job


@pytest.mark.sqlite_store
@posix
def test_a_green_release_is_built_alongside_switched_and_recorded(world):
    job = (_queue(world, {"f": "two\n"}))
    ran = _worker_runs(job, world)
    assert ran["state"] == wq.RUNNING and ran["handed_off"]
    assert wq.get(job["id"])["state"] == wq.RUNNING
    assert [d["outcome"] for d in wq.settle_deploys()] == [deploy.DEPLOYED]
    done = wq.get(job["id"])
    assert done["state"] == wq.DONE and done["rc"] == 0
    d = _deploys()[0]
    assert (d["outcome"], d["sha"], d["previous_sha"]) == (deploy.DEPLOYED, job["output"], world["first"])
    assert world["link"].is_symlink() and world["link"].resolve() == Path(d["release"]).resolve()
    assert _git(world["link"], "rev-parse", "HEAD") == job["output"]
    assert (world["link"] / "evals" / "cases" / "stt" / "clip.yaml").read_text(encoding="utf-8") == "imported\n"
    assert not (world["link"] / ".venv" / "big").exists()
    assert Path(d["previous"]).name == f"adopted-{world['first'][:12]}"
    assert d["backup"] == "" and _schema() == ms.SCHEMA_VERSION
    assert not wq.paused()
    steps = world["log"].read_text(encoding="utf-8").splitlines()
    rel = Path(d["release"]).name
    # The smoke before the switch warns on a property the release introduces; the switch's smoke enforces it (#1608).
    # Non-model GGUFs leave the router dir before each smoke, so a stray download fails no deploy (#1674).
    assert steps == [f"repair {rel}", f"smoke {rel} before", f"reinstall {rel}", f"repair {rel}", f"smoke {rel} after"]


@pytest.mark.sqlite_store
@posix
def test_a_release_whose_smoke_fails_after_the_switch_rolls_back_and_restores_the_store(world):
    job = (_queue(world, {"fail-smoke-live": "",
                                "harness/memory_store/schema.py": f"SCHEMA_VERSION = {ms.SCHEMA_VERSION + 1}\n"}))
    _worker_runs(job, world)
    restored = _deploys()[0]
    assert restored["stage"] == "migrating" and restored["backup"], "the restore kept the row's own backup"
    wq.settle_deploys()
    d = _deploys()[0]
    assert d["outcome"] == deploy.ROLLED_BACK and d["rolled_back_from"] == job["output"]
    assert (d["schema_from"], d["schema_to"]) == (ms.SCHEMA_VERSION, ms.SCHEMA_VERSION + 1)
    assert Path(d["backup"]).is_file()
    assert world["link"].resolve() == Path(d["previous"]).resolve()
    assert _git(world["link"], "rev-parse", "HEAD") == world["first"]
    assert _schema() == ms.SCHEMA_VERSION and "planted_by_migration" not in _tables()
    assert wq.get(job["id"])["state"] == wq.FAILED
    assert not wq.paused()
    steps = world["log"].read_text(encoding="utf-8")
    prev, rel = Path(d["previous"]).name, Path(d["release"]).name
    # The rollback smoke follows the new release's repair too: the previous release may not have the verb (#1674).
    assert f"reinstall {rel}\nrepair {rel}\nreinstall {prev}\nrepair {rel}\nsmoke {prev} after\n" in steps
    assert f"alert deploy of {job['output'][:12]} rolled_back" in steps


@pytest.mark.sqlite_store
@posix
def test_a_release_whose_smoke_fails_before_the_switch_never_switches_or_migrates(world):
    job = (_queue(world, {"fail-smoke": "",
                                "harness/memory_store/schema.py": f"SCHEMA_VERSION = {ms.SCHEMA_VERSION + 1}\n"}))
    ran = _worker_runs(job, world)
    assert ran["state"] == wq.FAILED and ran["rc"] == 1
    d = _deploys()[0]
    assert d["outcome"] == deploy.FAILED and "smoke before the switch" in d["detail"]
    assert d["backup"] == "" and _schema() == ms.SCHEMA_VERSION
    assert _git(world["link"], "rev-parse", "HEAD") == world["first"]
    assert "reinstall" not in world["log"].read_text(encoding="utf-8")
    assert not wq.paused()


@posix
def test_the_switch_steps_run_in_the_recorded_install_environment_not_the_workers(world, monkeypatch):
    """#1518: launchd gave the switch no profile, so reinstall rendered units from an in-release hf_root."""
    rec = paths.home() / deploy_switch.INSTALL_ENV
    rec.write_text(rec.read_text(encoding="utf-8") + "LH_DAY_FETCH=1\n", encoding="utf-8")
    monkeypatch.setenv("LH_DAY_FETCH", "0")
    job = _queue(world, {"scripts/launchd.sh": 'echo "reinstall hf=$HF_HOME fetch=$LH_DAY_FETCH" >> "$DEPLOY_LOG"\n'})
    monkeypatch.setenv("HF_HOME", str(world["link"] / "hf_root"))
    _worker_runs(job, world)
    assert [d["outcome"] for d in wq.settle_deploys()] == [deploy.DEPLOYED]
    said = [ln for ln in world["log"].read_text(encoding="utf-8").splitlines() if ln.startswith("reinstall")]
    assert said == [f"reinstall hf={world['hf']} fetch=1"]


@posix
@pytest.mark.parametrize("record", ["missing", "unreadable"])
def test_a_deploy_without_a_usable_install_record_stops_before_it_builds(world, record):
    rec = paths.home() / deploy_switch.INSTALL_ENV
    if record == "missing":
        rec.unlink()
    else:
        rec.write_text(f"HF_HOME={world['hf'] / 'gone'}\n", encoding="utf-8")
    job = _queue(world, {"f": "two\n"})
    ran = _worker_runs(job, world)
    assert ran["state"] == wq.FAILED and ran["rc"] == 1
    d = _deploys()[0]
    assert d["outcome"] == deploy.FAILED and "reinstall would refuse" in d["detail"]
    assert ("no recorded install environment" if record == "missing" else "cannot be read") in d["detail"]
    assert not world["link"].is_symlink()
    said = world["log"].read_text(encoding="utf-8").splitlines()
    assert len(said) == 1 and said[0].startswith("alert ") and "reinstall would refuse" in said[0], said
    assert not deploy.releases_dir().exists() or not any(deploy.releases_dir().iterdir())


# --- the worker restarting mid-deploy ------------------------------------------------------------------------------


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    return p.pid


@posix
@pytest.mark.parametrize("ending", ["deployed", "switch died", "switch alive"])
def test_the_runner_restarting_mid_deploy_leaves_no_job_running(world, ending, alerts):
    job = (_queue(world, {"f": "two\n"}))
    handed = []
    _worker_runs(job, world, spawn=lambda path, release: handed.append(path) or "launchd")
    assert wq.paused() and wq.get(job["id"])["state"] == wq.RUNNING
    rec = deploy_switch.load(handed[0])
    if ending == "deployed":
        rec.update(outcome=deploy.DEPLOYED, detail="serving", finished_at=time.time(), pid=_dead_pid())
    elif ending == "switch died":
        rec.update(stage="switching", pid=_dead_pid())
    else:
        rec.update(stage="switching", pid=os.getpid())
    deploy_switch.save(handed[0], rec)
    wq.run_pending(popen=lambda *a, **k: pytest.fail("nothing else may start"), gate=lambda: (False, "paused"))
    state = wq.get(job["id"])["state"]
    d = _deploys()[0]
    if ending == "deployed":
        assert (state, d["outcome"]) == (wq.DONE, deploy.DEPLOYED)
    elif ending == "switch died":
        assert (state, d["outcome"]) == (wq.FAILED, deploy.INTERRUPTED)
        assert "without an outcome" in d["detail"] and not wq.paused()
        assert len(alerts) == 1 and "interrupted" in alerts[0]
    else:
        assert (state, d["outcome"]) == (wq.RUNNING, "")
        rec.update(outcome=deploy.DEPLOYED, detail="serving", finished_at=time.time())
        deploy_switch.save(handed[0], rec)
        wq.serve(forever=False, gate_fn=lambda: (False, "paused"))
        assert wq.get(job["id"])["state"] == wq.DONE


def test_a_deploy_job_cut_off_before_its_handoff_is_settled_failed():
    job = _pending_deploy()
    _claim(job)
    with wq._store() as c:
        deploy._insert(c, job["output"], int(job["id"]), paths.home(), "", time.time())
    other = wq.add(["true"], title="cut off too", cwd=str(paths.home()))
    _claim(other)
    wq._recover()
    assert wq.get(job["id"])["state"] == wq.FAILED and wq.get(other["id"])["state"] == wq.FAILED
    d = _deploys()[0]
    assert d["outcome"] == deploy.INTERRUPTED and "before it handed off" in d["detail"]


def test_a_deploy_job_cut_off_before_it_recorded_a_deploy_is_settled_failed():
    job = _pending_deploy()
    _claim(job)
    wq._recover()
    got = wq.get(job["id"])
    assert got["state"] == wq.FAILED and "before it recorded a deploy" in got["note"]


def test_a_handed_off_switch_gets_its_grace_before_it_reads_as_dead():
    job = _pending_deploy()
    _claim(job)
    with wq._store() as c:
        did = deploy._insert(c, job["output"], int(job["id"]), paths.home(), "", time.time())
    deploy_switch.save(deploy.record_path(did), {"stage": "handed_off", "handed_at": time.time(), "outcome": "",
                                                 "link": str(paths.home()), "queue_flag": str(wq._pause_flag())})
    assert deploy.settle() == [] and wq.get(job["id"])["state"] == wq.RUNNING
    assert deploy.settle(now=time.time() + deploy.HANDOFF_GRACE_S + 1)[0]["outcome"] == deploy.INTERRUPTED


# --- pieces ------------------------------------------------------------------------------------------------------


@posix
def test_prune_keeps_the_serving_and_previous_releases(world, monkeypatch):
    monkeypatch.setattr(deploy, "KEEP_RELEASES", 2)
    root = deploy.releases_dir()
    for name in ("adopted-aaa", "3-bbb", "7-ccc", "9-ddd"):
        (root / name).mkdir(parents=True)
    assert deploy.prune({root / "3-bbb", root / "9-ddd"}, world["link"], room=1) == ["adopted-aaa", "7-ccc"]
    assert sorted(p.name for p in root.iterdir()) == ["3-bbb", "9-ddd"]
    assert deploy.prune({root / "9-ddd"}, world["link"], room=1) == ["3-bbb"]


def test_prune_keeps_the_newest_store_backups(monkeypatch):
    monkeypatch.setattr(deploy, "KEEP_RELEASES", 2)
    for i in (2, 11, 7):
        (deploy.backups_dir() / f"discovery-{i}-pre89.db").write_text("", encoding="utf-8")
    assert deploy.prune_backups() == ["discovery-2-pre89.db"]
    assert sorted(p.name for p in deploy.backups_dir().iterdir()) == ["discovery-11-pre89.db", "discovery-7-pre89.db"]


@pytest.mark.sqlite_store
def test_restore_puts_the_backup_over_the_live_store(tmp_path):
    db = ms.db_path()
    ms.connect().close()
    saved = deploy.backup(db, tmp_path / "pre.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE later (x)")
    c.commit()
    c.close()
    assert deploy_switch.restore(saved, db) == ms.SCHEMA_VERSION
    assert "later" not in _tables()


@pytest.mark.skipif(sys.platform != "darwin", reason="the switch is a launchd one-shot only on macOS")
def test_the_switch_is_a_launchd_one_shot_that_outlives_the_worker(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "calls"
    (bin_ / "launchctl").write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n', encoding="utf-8")
    (bin_ / "launchctl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    record = tmp_path / "1.json"
    assert deploy.spawn_switch(record, tmp_path) == f"launchd {deploy.SWITCH_LABEL}"
    import plistlib
    plist = plistlib.loads((paths.home() / "launchd" / f"{deploy.SWITCH_LABEL}.plist").read_bytes())
    assert plist["ProgramArguments"][3:] == ["-I", str(Path(deploy_switch.__file__).resolve()), str(record)]
    assert plist["RunAtLoad"] is True and "KeepAlive" not in plist
    said = calls.read_text(encoding="utf-8").splitlines()
    assert said[0].startswith("bootout ") and said[1].startswith("bootstrap ")


def test_the_switch_imports_nothing_outside_the_stdlib_but_its_lifecycle_table():
    out = subprocess.run([sys.executable, "-I", "-c", "import runpy, sys; runpy.run_path(sys.argv[1]); "
                          "print(sorted(m for m in sys.modules if m.startswith('harness')))",
                          deploy_switch.__file__], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "['harness', 'harness.deploy_state', 'harness.proc_identity']"


def test_morning_names_a_deploy_that_did_not_deploy():
    from harness import morning
    with wq._store() as c:
        did = deploy._insert(c, "a" * 40, None, paths.home(), "b" * 40, time.time())
        deploy.finish(c, did, deploy.ROLLED_BACK, "smoke failed", rolled_back_from="a" * 40)
        rows = morning.deploys_since(c, 0)
    needs = morning.needs({"deploys": rows, "sweep": {"loop": None}, "deploy": {}, "stale": [],
                           "ci": {}, "watchdog": [], "incidents": []})
    assert any(n.startswith(f"deploy {did} aaaaaaaaaaaa") and "rolled_back from aaaaaaaaaaaa to bbbbbbbbbbbb" in n
               for n in needs)


def test_reverify_reads_a_queue_deploy_as_the_code_changing(monkeypatch):
    from harness import reverify
    monkeypatch.setattr(reverify, "_committed_at", lambda: 100.0)
    with wq._store() as c:
        job = wq.add(["true"], title="rerun", cwd=str(paths.home()), conn=c)
        c.execute("UPDATE jobs SET started_at = 200 WHERE id = ?", (int(job["id"]),))
        last = {"outcome": reverify.UNRUN, "run_id": None, "job_id": int(job["id"]), "queued_at": 150.0}
        assert not reverify._harness_moved(c, last)
        did = deploy._insert(c, "a" * 40, None, paths.home(), "", 250.0)
        deploy.finish(c, did, deploy.DEPLOYED, "serving", now=300.0)
        assert reverify._harness_moved(c, last)


def test_the_launchd_units_poll_for_deploys_and_reinstall_skips_the_checkout():
    text = (Path(__file__).resolve().parents[1] / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    assert " deploy\"" in text.split("SERVICES=", 1)[1].splitlines()[0]
    body = text.split("install_units() {", 1)[1].split("\n}\n", 1)[0]
    assert body.index('if [ "${1:-}" != reinstall ]') < body.index("    deploy\n")
    assert "install_units reinstall ;;" in text
    assert json.loads(json.dumps(deploy.Steps().install)) == ["bash", "scripts/launchd.sh", "reinstall"]
