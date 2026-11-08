"""A deploy is a work-queue job: each green main commit is built alongside, switched, verified, or rolled back. #1506.

Releases are git worktrees under $LH_HOME/releases; scripts/launchd.sh's DEPLOY becomes a link to the one serving.
The job builds and smokes the new release in place, backs the store up and migrates it, then hands the switch to
harness/deploy_switch.py, which outlives the worker restart. The worker settles the job from the switch's record.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from harness import deploy_switch, paths
from harness import workqueue as wq

KIND = "deploy"
#: Ahead of every measurement job; a deploy still never interrupts a running one.
PRIORITY = 1000
#: A job that handed its switch to deploy_switch exits with this; the worker leaves it running for settle().
HANDED_OFF = 76
#: Release directories kept, the serving and the previous one included.
KEEP_RELEASES = 3
#: How long one git command of a deploy may take (fetch, worktree add, ls-files).
GIT_TIMEOUT_S = 300.0
#: How long `uv sync --frozen` may take in a new release.
SYNC_TIMEOUT_S = 1800.0
#: How long scripts/smoke.sh may take against the new release, before the switch.
SMOKE_TIMEOUT_S = 1200.0
#: How long the new release's migration of the live store may take.
MIGRATE_TIMEOUT_S = 1800.0
#: How long a handed-off switch may take to start and record its pid before settle calls the deploy interrupted.
HANDOFF_GRACE_S = 300.0
#: How long launchctl may take to load the switch's one-shot unit.
LAUNCHCTL_TIMEOUT_S = 60.0
SWITCH_LABEL = "com.unxmaal.localharness.deploy-switch"
SMOKE_PHASE_ENV = deploy_switch.SMOKE_PHASE_ENV
DEPLOYED, ROLLED_BACK, FAILED, INTERRUPTED = (deploy_switch.DEPLOYED, deploy_switch.ROLLED_BACK,
                                              deploy_switch.FAILED, "interrupted")
#: Untracked paths a release does not inherit from the one before it: rebuilt, or caches.
NOT_CARRIED = frozenset({".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"})
SOH = ("uv", "run", "python", "-m", "harness.cli")


class DeployError(RuntimeError):
    pass


@dataclass
class Steps:
    """The commands a deploy runs, each in the release named; tests plant their own."""
    sync: list = field(default_factory=lambda: ["uv", "sync", "--frozen"])
    smoke: list = field(default_factory=lambda: ["bash", "scripts/smoke.sh"])
    migrate: list = field(default_factory=lambda: [*SOH, "deploy", "migrate"])
    coherence: list = field(default_factory=lambda: [*SOH, "coherence"])
    install: list = field(default_factory=lambda: ["bash", "scripts/launchd.sh", "reinstall"])
    alert: list = field(default_factory=lambda: ["bash", "scripts/monit-alert.sh", "deploy"])


def releases_dir() -> Path:
    return paths.home() / "releases"


def records_dir() -> Path:
    d = paths.home() / "deploys"
    d.mkdir(parents=True, exist_ok=True)
    return d


def record_path(deploy_id: int) -> Path:
    return records_dir() / f"{int(deploy_id)}.json"


def backups_dir() -> Path:
    d = paths.home() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pause_flag() -> Path:
    return wq.root() / "deploy-paused"


def paused() -> bool:
    return _pause_flag().exists()


def pause() -> None:
    _pause_flag().write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")


def resume() -> None:
    _pause_flag().unlink(missing_ok=True)


def blocked(running=None) -> str:
    """Why a deploy may not start now, or ''; the queue also holds it behind the contention gate (#1509)."""
    if paused():
        return "deploys are paused (soh deploy resume)"
    from harness import sweep_guard
    found = (running or sweep_guard.running)(paths.home())
    if found:
        return "waiting for " + "; ".join(sweep_guard.describe(r) for r in found)
    return ""


def _env(extra=None) -> dict:
    return {**deploy_switch.env(), **(extra or {})}


def _git(cwd, *args: str) -> str:
    from harness import cuts
    try:
        with cuts.timeout("harness/deploy.py:GIT_TIMEOUT_S", f"git {' '.join(args[:2])}"):
            got = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                                 timeout=GIT_TIMEOUT_S, env=_env())
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeployError(f"git {' '.join(args)}: {exc}") from exc
    if got.returncode != 0:
        raise DeployError(f"git {' '.join(args)} failed: {(got.stderr or got.stdout).strip()[:300]}")
    return got.stdout.strip()


def head_of(path) -> str:
    try:
        return _git(path, "rev-parse", "HEAD")
    except DeployError:
        return ""


def origin_main(src) -> str:
    _git(src, "fetch", "-q", "origin", "main")
    return _git(src, "rev-parse", "origin/main")


def _store_schema(conn) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    return int(row[0]) if row else 0


def _jobs_for(conn, sha: str) -> list:
    return conn.execute("SELECT id, state FROM jobs WHERE kind = ? AND output = ? ORDER BY id",
                        (KIND, sha)).fetchall()


def poll(conn=None, now: float | None = None, *, src=None, sha: str = "", force: bool = False,
         green=None, environ=None) -> dict:
    """Queue one deploy job for origin/main's head (or sha) when it passed check-macos; supersede pending older ones."""
    from harness import deploy_guard
    environ = os.environ if environ is None else environ
    if paused() and not force:
        return {"queued": None, "why": "deploys are paused (soh deploy resume)", "superseded": []}
    src = Path(src) if src is not None else paths.deploy_checkout()
    if src is None or not (src / ".git").exists():
        return {"queued": None, "why": "no deploy checkout on this machine", "superseded": []}
    try:
        want = sha or origin_main(src)
    except DeployError as exc:
        return {"queued": None, "why": str(exc), "superseded": []}
    if want == head_of(src) and not force:
        return {"queued": None, "why": f"{want[:12]} is already deployed", "superseded": []}
    with wq._store(conn) as c:
        seen = _jobs_for(c, want)
        live = [r for r in seen if r["state"] in (wq.PENDING, wq.RUNNING)]
        if live or (seen and not force):
            r = (live or seen)[-1]
            return {"queued": None, "why": f"{want[:12]} is already queued as job {wq.label(r['id'])} ({r['state']})",
                    "superseded": []}
        if environ.get(deploy_guard.OVERRIDE) != "1":
            ok, why = (green or deploy_guard.verdict)(want)
            if not ok:
                return {"queued": None, "why": why, "superseded": []}
        superseded = [wq.label(r["id"]) for r in c.execute(
            "SELECT id FROM jobs WHERE kind = ? AND state = ? AND output != ?", (KIND, wq.PENDING, want))]
        c.execute("UPDATE jobs SET state = ?, finished_at = ?, note = ? WHERE kind = ? AND state = ? AND output != ?",
                  (wq.CANCELLED, time.time() if now is None else now, f"superseded by {want[:12]}", KIND,
                   wq.PENDING, want))
        c.commit()
        job = wq.add([*SOH, "deploy", "run", want], title=f"deploy {want[:12]}", cwd=str(src), kind=KIND,
                     output=want, priority=PRIORITY, requested_by="deploy", conn=c)
    return {"queued": job, "why": "", "superseded": superseded}


def _insert(conn, sha: str, job_id, previous: Path, previous_sha: str, now: float) -> int:
    from harness import memory_store as ms
    cur = conn.execute("INSERT INTO deploys (sha, job_id, machine_id, previous, previous_sha, stage, started_at) "
                       "VALUES (?,?,?,?,?,?,?)", (sha, job_id, ms.remember_machine(conn), str(previous),
                                                  previous_sha, "building", now))
    conn.commit()
    return int(cur.lastrowid)


def _update(conn, deploy_id: int, **cols) -> None:
    sets = ", ".join(f"{k} = ?" for k in cols)
    conn.execute(f"UPDATE deploys SET {sets} WHERE id = ?", (*cols.values(), int(deploy_id)))
    conn.commit()


def finish(conn, deploy_id: int, outcome: str, detail: str, now: float | None = None,
           rolled_back_from: str = "") -> None:
    _update(conn, deploy_id, outcome=outcome, stage=outcome, detail=detail[:2000],
            finished_at=time.time() if now is None else now, rolled_back_from=rolled_back_from)


def adopt(link: Path) -> Path:
    """Move a plain deploy checkout into releases/ and leave a link in its place: the first queue deploy's layout."""
    sha = head_of(link)
    dest = releases_dir() / f"adopted-{(sha or 'unknown')[:12]}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.with_name(f".{link.name}.adopt")
    if tmp.is_symlink():
        tmp.unlink()
    os.symlink(dest, tmp)
    os.rename(link, dest)
    os.replace(tmp, link)
    try:
        _git(dest, "worktree", "repair")
    except DeployError as exc:
        print(f"deploy: {exc}; git still finds {dest} through the link", file=sys.stderr)
    return dest


def carry(src: Path, dst: Path) -> list[str]:
    """Copy the untracked files of src a release needs (imported cases, generated config) into dst."""
    out = _git(src, "ls-files", "--others", "--directory", "--no-empty-directory", "-z")
    carried = []
    for rel in filter(None, out.split("\0")):
        parts = Path(rel.rstrip("/")).parts
        if not parts or NOT_CARRIED & set(parts):
            continue
        a, b = src / rel, dst / rel
        if a.is_symlink() or a.is_file():
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a, b, follow_symlinks=False)
        elif a.is_dir():
            shutil.copytree(a, b, symlinks=True, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*NOT_CARRIED))
        else:
            continue
        carried.append(rel)
    return carried


def _order(p: Path) -> int:
    head = p.name.split("-", 1)[0]
    return int(head) if head.isdigit() else -1


def prune(keep: set, src: Path, room: int = 0, log=None, holding=None) -> list[str]:
    """Remove the oldest release directories past KEEP_RELEASES less `room`, never one in keep or one a live process runs from."""
    from harness import cuts, holders
    root = releases_dir()
    if not root.is_dir():
        return []
    have = sorted((p for p in root.iterdir() if p.is_dir()), key=_order)
    keep = {Path(k).resolve() for k in keep}
    spare = [p for p in have if p.resolve() not in keep]
    drop = spare[:max(0, len(have) - max(1, KEEP_RELEASES - room))]
    held = (holding or holders.holding)(drop) if drop else {}
    for p in list(drop):
        if held is not None and not held.get(p):
            continue
        why = ("no way to tell on this platform which live processes run from it" if held is None
               else f"{len(held[p])} live process(es) run from it: {'; '.join(held[p][:3])}")
        if log is not None:
            log.write(f"kept release {p.name} past KEEP_RELEASES: {why}\n")
        cuts.cut("harness/deploy.py:KEEP_RELEASES", f"release {p.name} kept: {why}", kept=1, dropped=0)
        drop.remove(p)
    gone = []
    for p in drop:
        try:
            _git(src, "worktree", "remove", "--force", str(p))
        except DeployError:
            shutil.rmtree(p, ignore_errors=True)
        gone.append(p.name)
    if drop:
        cuts.cut("harness/deploy.py:KEEP_RELEASES", "release directories", kept=len(have) - len(drop),
                 dropped=len(drop))
    return gone


def prune_backups() -> list[str]:
    """Keep the newest KEEP_RELEASES pre-migration store backups, one per migrating deploy."""
    def order(p: Path) -> int:
        head = p.name.split("-")[1] if p.name.count("-") >= 2 else ""
        return int(head) if head.isdigit() else -1
    have = sorted(backups_dir().glob("discovery-*-pre*.db"), key=order)
    drop = have[:max(0, len(have) - KEEP_RELEASES)]
    for p in drop:
        p.unlink(missing_ok=True)
    if drop:
        from harness import cuts
        cuts.cut("harness/deploy.py:KEEP_RELEASES", "pre-migration store backups", kept=len(have) - len(drop),
                 dropped=len(drop))
    return [p.name for p in drop]


def _run(argv, cwd, timeout: float, log, extra=None, *, site_knob: str) -> str:
    """'' when argv exited 0 in cwd, else why."""
    from harness import cuts
    log.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} in {cwd}: {' '.join(map(str, argv))}\n")
    log.flush()
    try:
        with cuts.timeout(site_knob, f"deploy step {argv[-1]}"):
            got = subprocess.run([str(a) for a in argv], cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                                 env=_env(extra), timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"{' '.join(map(str, argv))} timed out after {timeout:.0f} s"
    except OSError as exc:
        return f"{' '.join(map(str, argv))} could not run: {exc}"
    return "" if got.returncode == 0 else f"{' '.join(map(str, argv))} exited rc {got.returncode}"


def backup(db: Path, dest: Path) -> Path:
    """A consistent copy of the store: SQLite's backup API from a mode=ro connection, or pg_dump on Postgres."""
    from harness import store
    if store.backend() == store.POSTGRES:
        from harness import store_service
        return store_service.dump(dest)
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return dest


def switch_argv(record: Path) -> list[str]:
    """This release's deploy_switch as a file under the venv's base interpreter, isolated: no venv, no PYTHONPATH."""
    return [os.path.realpath(sys.executable), "-I", str(Path(deploy_switch.__file__).resolve()), str(record)]


def spawn_switch(record: Path, release_for_log: Path) -> str:
    """Start deploy_switch on the record so it outlives the worker: a launchd one-shot on macOS, else detached."""
    argv = switch_argv(record)
    log = paths.logs() / "deploy.log"
    if sys.platform == "darwin":
        import plistlib
        plist = paths.home() / "launchd" / f"{SWITCH_LABEL}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        keep = {k: os.environ[k] for k in ("PATH", "HOME", paths.ENV_VAR) if os.environ.get(k)}
        plist.write_bytes(plistlib.dumps({
            "Label": SWITCH_LABEL, "ProgramArguments": argv, "RunAtLoad": True,
            "WorkingDirectory": str(release_for_log), "StandardOutPath": str(log), "StandardErrorPath": str(log),
            "EnvironmentVariables": {**keep, "PYTHONUNBUFFERED": "1"}, "ProcessType": "Interactive"}))
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", f"{domain}/{SWITCH_LABEL}"], capture_output=True,
                       timeout=LAUNCHCTL_TIMEOUT_S)
        got = subprocess.run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True, text=True,
                             timeout=LAUNCHCTL_TIMEOUT_S)
        if got.returncode != 0:
            raise DeployError(f"launchctl bootstrap {plist}: {(got.stderr or got.stdout).strip()[:300]}")
        return f"launchd {SWITCH_LABEL}"
    with open(log, "a", encoding="utf-8") as out:
        child = wq.spawn_group(argv, str(release_for_log), out, _env())
    return f"pid {child.pid}"


def run(sha: str, job_id=None, *, conn=None, link: Path | None = None, steps: Steps | None = None,
        spawn=spawn_switch, now=time.time) -> int:
    """The deploy job: build, smoke, back up and migrate, then hand off the switch; HANDED_OFF, or 1 when it stopped."""
    from harness import memory_store as ms
    steps = steps or Steps()
    link = Path(link) if link is not None else paths.deploy_link()
    if link is None or not (link / ".git").exists():
        print("deploy: no deploy checkout on this machine", file=sys.stderr)
        return 1
    with wq._store(conn) as c:
        previous = link.resolve()
        previous_sha = head_of(previous)
        deploy_id = _insert(c, sha, None if job_id is None else int(job_id), previous, previous_sha, now())
        log_path = paths.logs() / "deploy.log"
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"=== deploy {deploy_id} of {sha[:12]} {time.strftime('%Y-%m-%dT%H:%M:%S')} ===\n")

            def stop(why: str) -> int:
                finish(c, deploy_id, FAILED, why, now())
                log.write(f"--- failed: {why}\n")
                log.flush()
                _alert(steps, previous, f"deploy of {sha[:12]} failed before the switch: {why}", log)
                return 1

            from harness import install_env
            why = install_env.problem()
            if why:
                return stop(f"reinstall would refuse: {why}")
            try:
                if not link.is_symlink():
                    previous = adopt(link)
                    _update(c, deploy_id, previous=str(previous))
                release = releases_dir() / f"{deploy_id}-{sha[:12]}"
                prune({previous, link.resolve()}, previous, room=1, log=log)
                prune_backups()
                _git(previous, "fetch", "-q", "origin", "main")
                _git(previous, "worktree", "add", "-q", "--detach", str(release), sha)
                _update(c, deploy_id, release=str(release))
                log.write(f"carried {', '.join(carry(previous, release)) or 'nothing'} from {previous}\n")
            except (DeployError, OSError) as exc:
                return stop(f"build: {exc}")
            why = _run(steps.sync, release, SYNC_TIMEOUT_S, log, site_knob="harness/deploy.py:SYNC_TIMEOUT_S")
            if why:
                return stop(why)
            _update(c, deploy_id, stage="smoking")
            why = _run(steps.smoke, release, SMOKE_TIMEOUT_S, log, {SMOKE_PHASE_ENV: "before"},
                       site_knob="harness/deploy.py:SMOKE_TIMEOUT_S")
            if why:
                return stop(f"smoke before the switch: {why}")
            have, want = _store_schema(c), wq.code_schema(release) or 0
            _update(c, deploy_id, schema_from=have, schema_to=max(have, want))
            saved, migrated = "", want > have
            if migrated:
                saved = str(backups_dir() / f"discovery-{deploy_id}-pre{want}.db")
                # Written before the copy, so a restored store still names its own backup.
                _update(c, deploy_id, stage="migrating", backup=saved)
                backup(ms.db_path(), Path(saved))
                why = _run(steps.migrate, release, MIGRATE_TIMEOUT_S, log, {paths.ALLOW_MIGRATE_ENV: "1"},
                           site_knob="harness/deploy.py:MIGRATE_TIMEOUT_S")
                if why:
                    deploy_switch.restore(Path(saved), ms.db_path())
                    return stop(f"migration to schema {want}: {why}; store restored from {saved}")
            rec = {"id": deploy_id, "sha": sha, "job_id": job_id, "link": str(link), "release": str(release),
                   "previous": str(previous), "previous_sha": previous_sha, "db": str(ms.db_path()),
                   "backup": saved, "migrated": migrated, "queue_was_paused": wq.paused(),
                   "queue_flag": str(wq._pause_flag()), "install": steps.install,
                   "rollback_install": steps.install, "verify": [steps.smoke, steps.coherence],
                   "alert": steps.alert, "log": str(log_path), "install_env": str(install_env.path()),
                   "stage": "handed_off", "outcome": "",
                   "handed_at": now()}
            wq.pause()
            path = record_path(deploy_id)
            deploy_switch.save(path, rec)
            _update(c, deploy_id, stage="switching")
            try:
                how = spawn(path, release)
            except (DeployError, OSError, subprocess.SubprocessError) as exc:
                if not rec["queue_was_paused"]:
                    wq.resume()
                path.unlink(missing_ok=True)
                if migrated:
                    deploy_switch.restore(Path(saved), ms.db_path())
                return stop(f"could not start the switch: {exc}")
            log.write(f"--- switch handed to {how}; record {path}\n")
    return HANDED_OFF


def _alert(steps: Steps, cwd: Path, message: str, log) -> None:
    rec = {"alert": steps.alert, "previous": str(cwd), "outcome": FAILED}
    deploy_switch.alert(rec, message, log)


def _read(path: Path) -> dict:
    try:
        return deploy_switch.load(path)
    except (OSError, ValueError):
        return {}


def settle(conn=None, now: float | None = None, alive=wq.alive) -> list[dict]:
    """Close every unfinished deploy of this machine whose job or switch has ended; a deploy job is never left running."""
    now = time.time() if now is None else now
    settled = []
    with wq._store(conn) as c:
        where, args = wq._here(c)
        for row in c.execute(f"SELECT * FROM deploys WHERE outcome = '' AND {where} ORDER BY id", args).fetchall():
            got = _settle_one(c, dict(row), now, alive)
            if got:
                settled.append(got)
        claimed, cargs = wq._claimed(c)
        for job in c.execute(f"SELECT id FROM jobs WHERE kind = ? AND state = ? AND {claimed} AND id NOT IN "
                             "(SELECT job_id FROM deploys WHERE job_id IS NOT NULL)", (KIND, wq.RUNNING, *cargs)):
            if wq._pid_of(job["id"]) is None:
                _close_job(c, job["id"], wq.FAILED, None, "interrupted before it recorded a deploy", now)
                settled.append({"job": wq.label(job["id"]), "outcome": INTERRUPTED})
    return settled


def _close_job(c, job_id, state: str, rc, note: str, now: float) -> None:
    c.execute("UPDATE jobs SET state = ?, rc = COALESCE(?, rc), finished_at = ?, note = ? WHERE id = ? AND state = ?",
              (state, rc, now, note[:2000], int(job_id), wq.RUNNING))
    c.commit()


def _settle_one(c, row: dict, now: float, alive) -> dict | None:
    rec = _read(record_path(row["id"]))
    job = wq.get(row["job_id"], conn=c) if row["job_id"] is not None else None
    if rec.get("outcome"):
        from harness import cuts
        for t in rec.get("timed_out") or []:
            site_knob = t["site"]
            cuts.cut(site_knob, t["what"], kept=0, dropped=1, conn=c)
        finish(c, row["id"], rec["outcome"], rec.get("detail", ""), rec.get("finished_at") or now,
               rec.get("rolled_back_from", ""))
        _update(c, row["id"], **{k: rec[k] for k in ("release", "previous", "backup") if rec.get(k)})
        if job is not None:
            ok = rec["outcome"] == DEPLOYED
            _close_job(c, job["id"], wq.DONE if ok else wq.FAILED, 0 if ok else 1,
                       f"deploy {row['id']} {rec['outcome']}: {rec.get('detail', '')}", now)
        return {"deploy": row["id"], "outcome": rec["outcome"]}
    if rec:
        if rec.get("pid") and alive(int(rec["pid"])):
            return None
        if rec.get("stage") == "handed_off" and now - float(rec.get("handed_at") or 0) < HANDOFF_GRACE_S:
            return None
        why = f"the switch stopped at {rec.get('stage')} without an outcome; the deploy link points at " \
              f"{os.path.realpath(rec['link'])}"
        if not rec.get("queue_was_paused"):
            Path(rec["queue_flag"]).unlink(missing_ok=True)
    else:
        if job is not None and job["state"] == wq.RUNNING and wq._pid_of(job["id"]) is not None:
            return None
        if job is not None and job["state"] != wq.RUNNING:
            why = f"job {job['id']} ended {job['state']} rc={job['rc']} before it recorded an outcome"
        else:
            why = "the job stopped before it handed off the switch"
    finish(c, row["id"], INTERRUPTED, why, now)
    if job is not None:
        _close_job(c, job["id"], wq.FAILED, None, f"deploy {row['id']} interrupted: {why}", now)
    _alert_here(f"deploy {row['id']} of {row['sha'][:12]} interrupted: {why}")
    return {"deploy": row["id"], "outcome": INTERRUPTED}


def _alert_here(message: str) -> None:
    from harness import monitor
    try:
        monitor.alert("deploy", {"MONIT_SERVICE": "deploy", "MONIT_DESCRIPTION": message})
    except (OSError, ValueError) as exc:
        print(f"deploy alert failed: {exc}", file=sys.stderr)


def recent(conn, days: float = 7.0) -> list[dict]:
    rows = conn.execute("SELECT * FROM deploys WHERE started_at >= ? ORDER BY id DESC",
                        (time.time() - days * 86400.0,)).fetchall()
    return [dict(r) for r in rows]


def since(conn, t: float) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM deploys WHERE started_at >= ? ORDER BY id", (float(t),))]


def deployed_at(conn) -> float | None:
    """When this machine's newest queue deploy finished serving its commit; None before the first."""
    from harness import memory_store as ms
    mid = ms.machine_row(conn)
    row = conn.execute("SELECT MAX(finished_at) FROM deploys WHERE outcome = ? AND (machine_id = ? OR machine_id "
                       "IS NULL)", (DEPLOYED, mid)).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def line(d: dict) -> str:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["started_at"]))
    out = d["outcome"] or f"running ({d['stage']})"
    back = f" from {d['rolled_back_from'][:12]} to {d['previous_sha'][:12]}" if d.get("rolled_back_from") else ""
    return f"deploy {d['id']} {d['sha'][:12]} {when}: {out}{back}" + (f"; {d['detail']}" if d.get("detail") else "")


def status(conn) -> dict:
    link = paths.deploy_link()
    return {"paused": paused(), "blocked": blocked(), "link": str(link) if link else "",
            "serving": str(link.resolve()) if link else "", "head": head_of(link) if link else "",
            "recent": recent(conn), "jobs": [j for j in wq.jobs(conn) if j["kind"] == KIND][-5:]}
