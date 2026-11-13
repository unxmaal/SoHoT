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

from harness import deploy_state as ds
from harness import deploy_switch, job_claim, job_procs, job_state as js, paths, proc_identity, queue_pause
from harness import workqueue as wq

KIND = "deploy"
#: Ahead of every measurement job; a due deploy pauses a running one at its checkpoint (#1672).
PRIORITY = 1000
#: Seconds after a sha's deploy job failed before the poll queues that sha again. #1672.
RETRY_S = 3600.0
#: Times a failed sha is queued again before only a new commit or --force deploys it. #1672.
RETRIES = 3
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
#: How long the new release's `launchd.sh probe` may take: its launchd agent reading the weights, PREFLIGHT_WAIT_S 60 at most.
PROBE_TIMEOUT_S = 300.0
#: How long the new release's migration of the live store may take.
MIGRATE_TIMEOUT_S = 1800.0
#: How long a deploy due to migrate waits, the queue paused, for every other job running here to end. #1795.
QUIESCE_TIMEOUT_S = 600.0
#: The detail of a deploy that stopped because a job still ran here when it was due to migrate; the store kept its schema.
NOT_QUIESCED = "not quiesced"
#: The durable steps before the switch, each named in the record as it is about to be taken. #1752.
PAUSE, BACKUP, MIGRATE, RECORD = "pause", "backup", "migrate", "record"
#: How long a handed-off switch may take to start and record its pid before settle calls the deploy interrupted.
HANDOFF_GRACE_S = 300.0
#: How long launchctl may take to load the switch's one-shot unit.
LAUNCHCTL_TIMEOUT_S = 60.0
SWITCH_LABEL = "com.unxmaal.localharness.deploy-switch"
#: How many times settle starts a dead switch again from the stage its record names before it calls the deploy interrupted. #1753.
RESUMES = 1
#: The switch unit's program: the one the Full Disk Access grant names, SIP-protected, so the grant never lapses. #1516.
SWITCH_SHELL = "/bin/bash"
SMOKE_PHASE_ENV = deploy_switch.SMOKE_PHASE_ENV
DEPLOYED, ROLLED_BACK, FAILED, FAILED_FORWARD, INTERRUPTED = (ds.DEPLOYED, ds.ROLLED_BACK, ds.FAILED,
                                                              ds.FAILED_FORWARD, ds.INTERRUPTED)
#: Untracked paths a release does not inherit from the one before it: rebuilt, or caches.
NOT_CARRIED = frozenset({".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"})
SOH = ("uv", "run", "python", "-m", "harness.cli")


class DeployError(RuntimeError):
    pass


@dataclass
class Steps:
    """The commands a deploy runs, each in the release named; tests plant their own."""
    sync: list = field(default_factory=lambda: ["uv", "sync", "--frozen"])
    probe: list = field(default_factory=lambda: ["bash", "scripts/launchd.sh", "probe"] if sys.platform == "darwin"
                        else [])
    smoke: list = field(default_factory=lambda: ["bash", "scripts/smoke.sh"])
    #: Before every smoke: drafters, MTP heads and shards leave the router dir, so a stray download fails no deploy. #1674.
    repair: list = field(default_factory=lambda: [*SOH, "gguf-aux", "--apply"])
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
    from harness import deploy_repair
    waiting = deploy_repair.lines(deploy_repair.pending())
    if waiting:
        return "; ".join(waiting)
    from harness import sweep_guard
    found = (running or sweep_guard.running)(paths.home())
    if found:
        return "waiting for " + "; ".join(sweep_guard.describe(r) for r in found)
    return ""


def _env(extra=None) -> dict:
    return {**deploy_switch.env(), **(extra or {})}


SUPERSEDED = "superseded by "


def _wait_alerted() -> Path:
    return wq.root() / "deploy-wait-alerted"


def waiting_since(conn, job_id) -> tuple[float, int]:
    """(when, first job id) deploys began waiting: this job's queueing, or that of the pending jobs it superseded. #1672."""
    key, since, first = int(job_id), None, int(job_id)
    for r in conn.execute("SELECT id, created_at, state, reason FROM jobs WHERE kind = ? AND id <= ? ORDER BY id DESC",
                          (KIND, key)).fetchall():
        if int(r["id"]) != key and not (r["state"] == wq.CANCELLED and r["reason"] == js.SUPERSEDED):
            break
        since, first = float(r["created_at"]), int(r["id"])
    return (time.time() if since is None else since), first


def wait(conn, now: float | None = None, sample=None) -> dict | None:
    """The pending deploy, since when deploys have waited and why it has not started ('' if it starts next poll). #1672."""
    from harness import contention
    now = time.time() if now is None else now
    job = next((j for j in wq.pending(conn) if j["kind"] == KIND), None)
    if job is None:
        return None
    since, first = waiting_since(conn, job["id"])
    why = held = blocked()
    if not why:
        ok, said = wq.gate(sample, now=now)
        why = "" if ok else said
    if not why:
        v = contention.verdict(conn, now, sample, since)
        why = "" if v["open"] else f"the contention gate is closed: {v['why']}"
    busy = [] if why else wq.running_here(conn)
    if busy:
        why = "waiting for the running job(s) " + ", ".join(j["id"] for j in busy)
    return {"job": job["id"], "sha": job["output"], "since": since, "first": first, "waited": now - since,
            "why": why, "held": bool(held)}


def wait_line(w: dict) -> str:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(w["since"]))
    return (f"deploy job {w['job']} of {w['sha'][:12]} pending since {when} ({w['waited'] / 3600:.1f} h): "
            + (w["why"] or "starts at the worker's next poll"))


def watch_wait(now: float | None = None, alert=None) -> dict | None:
    """One alert per wait once a pending deploy has waited contention.DEPLOY_ALERT_S, naming why; not for a pause or sweep. #1672."""
    from harness import contention, cuts
    now = time.time() if now is None else now
    try:
        said = _wait_alerted().read_text(encoding="utf-8").strip()
    except OSError:
        said = ""
    with wq._store() as c:
        job = next((j for j in wq.pending(c) if j["kind"] == KIND), None)
        since, first = waiting_since(c, job["id"]) if job is not None else (now, None)
        if now - since < contention.DEPLOY_ALERT_S or said == str(first):
            return None
        w = wait(c, now)
    if w is None or not w["why"] or w["held"]:
        return None
    _wait_alerted().write_text(str(w["first"]), encoding="utf-8")
    cuts.cut("deploy_wait_alert", "pending deploy alerted as stuck", dropped=1)
    (alert or _alert_script)(wait_line(w))
    return w


def _alert_script(message: str, event: str = "waiting") -> None:
    """The alert through scripts/monit-alert.sh, as monit runs it. #1672."""
    extra = {"MONIT_SERVICE": "deploy", "MONIT_EVENT": event, "MONIT_DESCRIPTION": message}
    try:
        subprocess.run(Steps().alert, cwd=Path(__file__).resolve().parents[1], env={**os.environ, **extra},
                       capture_output=True, timeout=deploy_switch.ALERT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"deploy alert failed: {exc}", file=sys.stderr)


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


def newer(src, tip: str, live: str) -> list[str]:
    """main's first-parent commits newer than the live release, newest first; only the tip when live is off main. #1702."""
    if not live:
        return [tip]
    try:
        _git(src, "merge-base", "--is-ancestor", live, tip)
        return _git(src, "rev-list", "--first-parent", tip, f"^{live}").split() or [tip]
    except DeployError:
        return [tip]


def _store_schema(conn) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    return int(row[0]) if row else 0


def _jobs_for(conn, sha: str) -> list:
    return conn.execute("SELECT id, state, finished_at FROM jobs WHERE kind = ? AND output = ? ORDER BY id",
                        (KIND, sha)).fetchall()


def _held_alerted() -> Path:
    return wq.root() / "deploy-held-alerted"


def _held(conn, sha: str, job_id, alert=None) -> str:
    """Why the poll holds a sha its last job rolled back on unchanged audit inputs, alerting once per hold; else ''. #1805."""
    from harness import deploy_hold
    h = deploy_hold.held(conn, job_id)
    if h is None:
        return ""
    try:
        said = _held_alerted().read_text(encoding="utf-8").strip()
    except OSError:
        said = ""
    if said != str(job_id):
        _held_alerted().write_text(str(job_id), encoding="utf-8")
        (alert or (lambda m: _alert_script(m, "held")))(
            f"held: deterministic audit failure, waiting for a newer sha: {sha[:12]} rolled back as deploy "
            f"{h['deploy']} on {h['checks']} and what they read has not changed (soh deploy now deploys it anyway)")
    return h["why"]


def _retry(seen: list, now: float, conn=None, sha: str = "", alert=None) -> str:
    """'' when a sha whose last deploy job failed may be queued again now, else why not. #1672."""
    from harness import cuts
    last = seen[-1]
    if last["state"] != wq.FAILED:
        return f"is already queued as job {wq.label(last['id'])} ({last['state']})"
    held = _held(conn, sha, last["id"], alert) if conn is not None else ""
    if held:
        return held
    failed = sum(r["state"] == wq.FAILED for r in seen)
    if failed > RETRIES:
        cuts.cut("deploy_retries", "a failed sha not queued again", dropped=1)
        return (f"failed {failed} times as job(s) up to {wq.label(last['id'])}, past its {RETRIES} retries; "
                f"a new commit or `soh deploy now` deploys it")
    at = float(last["finished_at"] or now) + RETRY_S
    if now < at:
        return (f"failed as job {wq.label(last['id'])}; retry {failed} of {RETRIES} at "
                f"{time.strftime('%H:%M', time.localtime(at))}")
    cuts.cut("deploy_retry_after", f"a failed deploy retried, attempt {failed + 1}", kept=1)
    return ""


def _borrowed() -> Path:
    return wq.root() / "deploy-borrowed"


def confirm(own=None, alert=None) -> str:
    """For a sha queued on its PR's run: '' until main's own run concludes, then what it said; alerts a failure. #1684."""
    from harness import deploy_guard
    try:
        sha = _borrowed().read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    try:
        state, why = (own or deploy_guard.own)(sha)
    except (deploy_guard.GhError, ValueError, KeyError, TypeError) as exc:
        return f"cannot yet confirm {sha[:12]} by main's own run: {exc}"
    if state in (deploy_guard.WAITING, deploy_guard.NONE):
        return ""
    _borrowed().unlink(missing_ok=True)
    if state == deploy_guard.FAILED:
        line = (f"{sha[:12]} was queued to deploy on its PR's {deploy_guard.JOB} run and main's own run failed "
                f"(soh deploy status says whether it is live): {why}")
        (alert or (lambda m: _alert_script(m, "ci failed")))(line)
        return line
    return f"{sha[:12]}: main's own run is {state}: {why}"


def poll(conn=None, now: float | None = None, *, src=None, sha: str = "", force: bool = False,
         green=None, environ=None, own=None, alert=None) -> dict:
    """Queue one deploy job for the newest main commit since live (or sha) that passed check-macos; supersede pending older ones."""
    said = confirm(own, alert)
    return {**_queue(conn, now, src=src, sha=sha, force=force, green=green, environ=environ, alert=alert),
            "confirm": said}


def _queue(conn, now, *, src, sha: str, force: bool, green, environ, alert=None) -> dict:
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
    deployed = head_of(src)
    if want == deployed and not force:
        return {"queued": None, "why": f"{want[:12]} is already deployed", "superseded": []}
    wants = [want] if sha or want == deployed else newer(src, want, deployed)
    with wq._store(conn) as c:
        refused = []
        for want in wants:
            seen = _jobs_for(c, want)
            live = [r for r in seen if r["state"] in (wq.PENDING, wq.RUNNING)]
            why = (f"is already queued as job {wq.label(live[-1]['id'])} ({live[-1]['state']})" if live
                   else _retry(seen, time.time() if now is None else now, c, want, alert) if seen and not force
                   else "")
            if why:
                return {"queued": None, "why": "; ".join([*refused, f"{want[:12]} {why}"]), "superseded": []}
            by = deploy_guard.BY_MAIN
            if environ.get(deploy_guard.OVERRIDE) == "1":
                break
            ok, why, by = (*(green or (lambda s: deploy_guard.judge(s, repo=src)))(want), by)[:3]
            if ok:
                break
            refused.append(why)
        else:
            more = f"; nor did the {len(wants) - 1} older main commit(s) since live {deployed[:12]}" if len(wants) > 1 else ""
            return {"queued": None, "why": refused[0] + more, "superseded": []}
        superseded = [wq.label(r["id"]) for r in c.execute(
            "SELECT id FROM jobs WHERE kind = ? AND state = ? AND output != ?", (KIND, wq.PENDING, want)).fetchall()
            if js.move(c, r["id"], wq.PENDING, wq.CANCELLED, js.SUPERSEDED, f"{SUPERSEDED}{want[:12]}",
                       finished_at=time.time() if now is None else now)]
        c.commit()
        job = wq.add([*SOH, "deploy", "run", want], title=f"deploy {want[:12]}", cwd=str(src), kind=KIND,
                     output=want, priority=PRIORITY, requested_by="deploy", conn=c)
    if by == deploy_guard.BY_PR:
        _borrowed().write_text(want, encoding="utf-8")
    return {"queued": job, "why": "", "superseded": superseded}


def _insert(conn, sha: str, job_id, previous: Path, previous_sha: str, now: float) -> int:
    from harness import memory_store as ms
    ds.check(ds.NEW, ds.BUILDING, ds.JOB)
    cur = conn.execute("INSERT INTO deploys (sha, job_id, machine_id, previous, previous_sha, stage, started_at) "
                       "VALUES (?,?,?,?,?,?,?)", (sha, job_id, ms.remember_machine(conn), str(previous),
                                                  previous_sha, ds.BUILDING, now))
    conn.commit()
    return int(cur.lastrowid)


#: Columns a move may set beside the stage; None leaves one as it is.
_COLS = ("release", "previous", "backup", "schema_from", "schema_to", "detail", "finished_at", "rolled_back_from")


def move(conn, deploy_id: int, leaves: str, enters: str, writer: str, **cols) -> bool:
    """The one writer of a deploys row: refuses a move ds.MOVES does not list, else compare-and-swaps on the stage it leaves."""
    ds.check(leaves, enters, writer)
    bad = set(cols) - set(_COLS)
    if bad:
        raise ValueError(f"deploys has no movable column {sorted(bad)}")
    vals = [cols.get(k) for k in _COLS]
    cur = conn.execute("UPDATE deploys SET stage = ?, outcome = ?, release = COALESCE(?, release), "
                       "previous = COALESCE(?, previous), backup = COALESCE(?, backup), "
                       "schema_from = COALESCE(?, schema_from), schema_to = COALESCE(?, schema_to), "
                       "detail = COALESCE(?, detail), finished_at = COALESCE(?, finished_at), "
                       "rolled_back_from = COALESCE(?, rolled_back_from) WHERE id = ? AND stage = ? AND outcome = ''",
                       (enters, enters if enters in ds.OUTCOMES else "", *vals, int(deploy_id), leaves))
    conn.commit()
    return cur.rowcount == 1


def stage_of(conn, deploy_id: int) -> str:
    row = conn.execute("SELECT stage FROM deploys WHERE id = ?", (int(deploy_id),)).fetchone()
    return row["stage"] if row else ds.NEW


def finish(conn, deploy_id: int, outcome: str, detail: str, now: float | None = None,
           rolled_back_from: str = "", *, leaves: str | None = None, writer: str = ds.SETTLE) -> bool:
    """Close the row with its outcome through move(); False when another writer closed it first."""
    leaves = stage_of(conn, deploy_id) if leaves is None else leaves
    return move(conn, deploy_id, leaves, outcome, writer, detail=detail[:2000],
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


def _probe(argv, release: Path, log, log_path: Path) -> str:
    """'' when a launchd agent started from the release reads the weights, else why with the probe's FATAL line. #1516."""
    if not argv:
        return ""
    log.flush()
    start = log_path.stat().st_size
    why = _run(argv, release, PROBE_TIMEOUT_S, log, site_knob="harness/deploy.py:PROBE_TIMEOUT_S")
    if not why:
        return ""
    log.flush()
    said = [ln.strip() for ln in log_path.read_bytes()[start:].decode("utf-8", "replace").splitlines()
            if ln.startswith("FATAL")]
    return f"{why}: {said[0]}" if said else why


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


def switch_root(record: Path) -> Path:
    """The release the record installs when it ships a switch, so its own orchestration runs; else this one. #1786."""
    release = str(_read(Path(record)).get("release") or "")
    if release and (Path(release) / "harness" / "deploy_switch.py").is_file():
        return Path(release).resolve()
    return Path(deploy_switch.__file__).resolve().parents[1]


def _base_python(root: Path) -> str:
    venv = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return os.path.realpath(venv if venv.exists() else sys.executable)


def switch_argv(record: Path) -> list[str]:
    """The installed release's deploy_switch as a file under its venv's base interpreter, isolated: no venv, no PYTHONPATH."""
    root = switch_root(record)
    return [_base_python(root), "-I", str(root / "harness" / "deploy_switch.py"), str(record)]


def spawn_switch(record: Path, release_for_log: Path) -> str:
    """Start deploy_switch on the record so it outlives the worker: a launchd one-shot on macOS, else detached."""
    argv = switch_argv(record)
    return launch(argv, release_for_log, Path(argv[2]).parents[1])


def launch(argv: list[str], release_for_log: Path, root: Path) -> str:
    """Start argv on the switch's launchd one-shot label on macOS, else detached, so it outlives the worker."""
    log = paths.logs() / "deploy.log"
    if sys.platform == "darwin":
        import plistlib
        plist = paths.home() / "launchd" / f"{SWITCH_LABEL}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        keep = {k: os.environ[k] for k in ("PATH", "HOME", paths.ENV_VAR) if os.environ.get(k)}
        # A python program would be its own privacy identity, and its first read of /Volumes waits on a dialog. #1516.
        wrapper = Path(root) / "scripts" / "deploy-switch.sh"
        if not wrapper.is_file():
            wrapper = Path(deploy_switch.__file__).resolve().parents[1] / "scripts" / "deploy-switch.sh"
        plist.write_bytes(plistlib.dumps({
            "Label": SWITCH_LABEL, "ProgramArguments": [SWITCH_SHELL, str(wrapper), *argv], "RunAtLoad": True,
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
        child = job_procs.spawn_group(argv, str(release_for_log), out, _env())
    return f"pid {child.pid}"


def _quiesce(c, job_id, log, sleep=time.sleep) -> str:
    """'' once no job but this deploy runs here, else the jobs still running at QUIESCE_TIMEOUT_S. #1795."""
    from harness import cuts
    end, said = time.monotonic() + QUIESCE_TIMEOUT_S, False
    while True:
        left = [wq.label(j["id"]) for j in wq.running_here(c)
                if wq._key(j["id"]) != wq._key(job_id)
                and (job_procs._pid_of(j["id"]) is not None or job_claim.starting(j["id"]))]
        if not left:
            return ""
        if time.monotonic() >= end:
            cuts.cut("harness/deploy.py:QUIESCE_TIMEOUT_S", "deploy quiesce", kept=0, dropped=1, conn=c)
            return f"job {', '.join(left)} still running here after {QUIESCE_TIMEOUT_S:.0f} s"
        if not said:
            log.write(f"--- waiting up to {QUIESCE_TIMEOUT_S:.0f} s for job {', '.join(left)} before the migration\n")
            log.flush()
            said = True
        sleep(min(2.0, max(0.0, end - time.monotonic())))


def run(sha: str, job_id=None, *, conn=None, link: Path | None = None, steps: Steps | None = None,
        spawn=None, now=time.time, sleep=time.sleep) -> int:
    """The deploy job: build, smoke, back up and migrate, then hand off the switch; HANDED_OFF, or 1 when it stopped."""
    spawn = spawn or spawn_switch
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
        at = [ds.BUILDING]
        log_path = paths.logs() / "deploy.log"
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"=== deploy {deploy_id} of {sha[:12]} {time.strftime('%Y-%m-%dT%H:%M:%S')} ===\n")

            def go(to: str, **cols) -> None:
                if not move(c, deploy_id, at[0], to, ds.JOB, **cols):
                    raise DeployError(f"deploy {deploy_id} left {at[0]} under the job: {stage_of(c, deploy_id)}")
                at[0] = to

            held, rec, path = [], {}, record_path(deploy_id)

            def taking(step: str, **more) -> None:
                rec.update(taking=step, **more)
                deploy_switch.save(path, rec)

            def stop(why: str) -> int:
                if held and not held[0]:
                    queue_pause.resume()
                if not finish(c, deploy_id, FAILED, why, now(), leaves=at[0], writer=ds.JOB):
                    log.write(f"--- deploy {deploy_id} left {at[0]} under the job: {stage_of(c, deploy_id)}\n")
                if rec:
                    taking(rec["taking"], stage=FAILED, outcome=FAILED, detail=why[:2000], finished_at=now())
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
                    go(ds.BUILDING, previous=str(previous))
                release = releases_dir() / f"{deploy_id}-{sha[:12]}"
                prune({previous, link.resolve()}, previous, room=1, log=log)
                prune_backups()
                _git(previous, "fetch", "-q", "origin", "main")
                _git(previous, "worktree", "add", "-q", "--detach", str(release), sha)
                go(ds.BUILDING, release=str(release))
                log.write(f"carried {', '.join(carry(previous, release)) or 'nothing'} from {previous}\n")
            except (DeployError, OSError) as exc:
                return stop(f"build: {exc}")
            why = _run(steps.sync, release, SYNC_TIMEOUT_S, log, site_knob="harness/deploy.py:SYNC_TIMEOUT_S")
            if why:
                return stop(why)
            why = _probe(steps.probe, release, log, log_path)
            if why:
                return stop(f"launchd probe of the new release before the switch: {why}")
            try:
                go(ds.SMOKING)
            except DeployError as exc:
                return stop(str(exc))
            repaired = _run(steps.repair, release, SMOKE_TIMEOUT_S, log, site_knob="harness/deploy.py:SMOKE_TIMEOUT_S")
            log.write(f"--- repair before smoke: {repaired or 'done'}\n")
            why = _run(steps.smoke, release, SMOKE_TIMEOUT_S, log, {SMOKE_PHASE_ENV: "before"},
                       site_knob="harness/deploy.py:SMOKE_TIMEOUT_S")
            if why:
                return stop(f"smoke before the switch: {why}")
            # Each durable step below is recorded before it is taken, so settle can undo a death at any point. #1752.
            note = f"deploy {deploy_id} of {sha[:12]}"
            held.append(queue_pause.paused())
            rec.update({"id": deploy_id, "sha": sha, "job_id": job_id, "link": str(link), "release": str(release),
                        "previous": str(previous), "previous_sha": previous_sha, "db": str(ms.db_path()),
                        "backup": "", "migrated": False, "queue_was_paused": held[0], "pause_note": note,
                        "queue_flag": str(queue_pause._pause_flag()), "install": steps.install,
                        "rollback_install": steps.install, "verify": [steps.smoke, steps.coherence],
                        "repair": steps.repair, "alert": steps.alert, "log": str(log_path),
                        "install_env": str(install_env.path()), "stage": at[0], "outcome": "", "run_pid": os.getpid(),
                        "run_identity": proc_identity.identity(os.getpid())})
            taking(PAUSE)
            # Paused before the migration, so no job of this release starts against the new schema. #1795.
            queue_pause.pause(note)
            have, want = _store_schema(c), wq.code_schema(release) or 0
            schema = {"schema_from": have, "schema_to": max(have, want)}
            saved, migrated = "", want > have
            if migrated:
                why = _quiesce(c, job_id, log, sleep)
                if why:
                    return stop(f"{NOT_QUIESCED}: {why}; the store stays at schema {have}")
                saved = str(backups_dir() / f"discovery-{deploy_id}-pre{want}.db")
                taking(BACKUP, stage=ds.MIGRATING, backup=saved, **schema)
                # Written before the copy, so a restored store still names its own backup.
                try:
                    go(ds.MIGRATING, backup=saved, **schema)
                except DeployError as exc:
                    return stop(str(exc))
                backup(ms.db_path(), Path(saved))
                taking(MIGRATE, migrated=True)
                why = _run(steps.migrate, release, MIGRATE_TIMEOUT_S, log, {paths.ALLOW_MIGRATE_ENV: "1"},
                           site_knob="harness/deploy.py:MIGRATE_TIMEOUT_S")
                if why:
                    deploy_switch.restore(Path(saved), ms.db_path())
                    return stop(f"migration to schema {want}: {why}; store restored from {saved}")
            taking(RECORD, stage=ds.HANDED_OFF, handed_at=now())
            try:
                go(ds.HANDED_OFF, **({} if migrated else schema))
                how = spawn(path, release)
            except (DeployError, OSError, subprocess.SubprocessError) as exc:
                if migrated:
                    deploy_switch.restore(Path(saved), ms.db_path())
                    # The restore put the row back as the backup saw it.
                    at[0] = ds.MIGRATING
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


def _is(pid, ident, since, alive) -> bool:
    """Whether pid is still the process a record names: alive, and neither its identity nor its start time says another."""
    if not pid or not alive(int(pid)):
        return False
    if isinstance(ident, dict) and ident.get("pid") == int(pid):
        got = proc_identity.same(ident)
        if got is not None:
            return got
    # A record without an identity (an older switch wrote it): a process that began after the record did is not it. #1773.
    began = proc_identity.began(int(pid))
    return began is None or not since or began <= float(since)


def _running(rec: dict, now: float, alive) -> bool:
    """Whether the job or switch behind an outcome-less record may still be at work."""
    if _is(rec.get("pid"), rec.get("identity"), rec.get("switch_started"), alive):
        return True
    if rec.get("stage") in ds.JOB_STAGES and _is(rec.get("run_pid"), rec.get("run_identity"), None, alive):
        return True
    if rec.get("resumed_at") and now - float(rec["resumed_at"]) < HANDOFF_GRACE_S:
        return True
    return rec.get("stage") == ds.HANDED_OFF and now - float(rec.get("handed_at") or 0) < HANDOFF_GRACE_S


def _lift(rec: dict) -> str:
    """Lift the queue pause this deploy set, never one its owner set before or after it; what became of it."""
    flag = Path(rec.get("queue_flag") or queue_pause._pause_flag())
    if not flag.exists():
        return ""
    if rec.get("queue_was_paused"):
        return "the queue stays paused, as its owner had it"
    note = rec.get("pause_note")
    try:
        text = flag.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if note and note not in text:
        return "the queue stays paused: its owner paused it after the deploy did"
    flag.unlink(missing_ok=True)
    return "the queue pause it set is lifted"


def _schema_now(db) -> int:
    from harness import store
    conn = store.open_ro(db)
    try:
        return _store_schema(conn)
    finally:
        conn.close()


def _undo(rec: dict) -> tuple[str, bool]:
    """Bring the store back to the schema the linked release speaks from the recorded backup; (what it found, ok)."""
    from harness import memory_store as ms
    if not rec.get("backup"):
        return "", True
    link = rec.get("link") or paths.deploy_link()
    speaks = wq.code_schema(os.path.realpath(link)) if link else None
    db = Path(rec.get("db") or ms.db_path())
    have = _schema_now(db)
    if speaks is None:
        return f"the store is at schema {have} and no linked release says which schema it speaks", True
    if have <= speaks:
        return f"the linked release (schema {speaks}) reads the store at schema {have}, so it is not restored", True
    try:
        got = deploy_switch.restore(Path(rec["backup"]), db)
    except Exception as exc:  # noqa: BLE001 - any failure leaves the store ahead; said, and the queue stays paused
        return (f"the store at schema {have} is ahead of the linked release (schema {speaks}) and its restore from "
                f"{rec['backup']} FAILED ({deploy_switch.named(exc)})"), False
    return (f"the store was at schema {have}, ahead of the linked release (schema {speaks}); restored from "
            f"{rec['backup']} (schema {got})"), True


def _speaks(schema: int) -> bool:
    from harness.memory_store import migrations
    return schema <= migrations.SCHEMA_VERSION


def _stranded(rec: dict, path: Path, now: float, spawn) -> dict | None:
    """A dead switch past the migration: resumed here if this code cannot open the store, else STORE_AHEAD once spent. #1841."""
    from harness import deploy_repair
    got = deploy_repair.ahead(rec)
    if got is None:
        return None
    failed = ""
    if int(rec.get("resumed") or 0) < RESUMES:
        if _speaks(got["store"]):
            return None
        failed = _resume(rec, {"id": rec.get("id", path.stem)}, now, spawn)
        if not failed:
            return None
    else:
        rec.setdefault("timed_out", []).append({"site": "harness/deploy.py:RESUMES",
                                                "what": f"deploy {rec.get('id', path.stem)} resume"})
    why = f"the switch died at {rec['stage']} " + (f"and {failed}" if failed else "with no restart left")
    return deploy_repair.strand(rec, path, got, why, now)


def recover(now: float | None = None, alive=job_procs.alive, spawn=None) -> list[dict]:
    """Undo each deploy that died before its switch, end one whose dead switch left the store ahead; no store read. #1752."""
    now = time.time() if now is None else now
    out = []
    for path in sorted(records_dir().glob("*.json")):
        rec = _read(path)
        if not rec or rec.get("outcome") or _running(rec, now, alive):
            continue
        if rec.get("stage") in ds.SWITCH_STAGES:
            got = _stranded(rec, path, now, spawn or respawn)
            if got:
                out.append(got)
            continue
        if rec.get("stage") not in ds.JOB_STAGES:
            continue
        step = rec.get("taking") or rec["stage"]
        head = (f"the switch it handed off never started within {HANDOFF_GRACE_S:.0f} s" if step in (RECORD, ds.HANDED_OFF)
                else f"the job died at its {step} step, before the switch")
        found, ok = _undo(rec)
        lifted = _lift(rec) if ok else "the queue stays paused until the store is put right"
        why = "; ".join(filter(None, (head, found, lifted)))
        rec.update(stage=INTERRUPTED, outcome=INTERRUPTED, detail=why[:2000], finished_at=now)
        deploy_switch.save(path, rec)
        _alert_here(f"deploy {rec.get('id', path.stem)} of {str(rec.get('sha', ''))[:12]} interrupted: {why}")
        out.append({"deploy": rec.get("id", path.stem), "outcome": INTERRUPTED, "detail": why})
    return out


def respawn(record: Path, release_for_log: Path) -> str:
    """How settle starts a dead switch again: only from the live home, since the switch unit's label is the machine's."""
    if Path(paths.home()).resolve() != Path(paths.DEFAULT_HOME).resolve():
        raise DeployError(f"{paths.home()} is not the live home, so it starts no deploy switch")
    return spawn_switch(record, release_for_log)


def _resume(rec: dict, row: dict, now: float, spawn) -> str:
    """Start the switch again on its record, which goes on from the stage it died at; '' once started, else why not. #1753."""
    path = record_path(row["id"])
    rec.update(resumed=int(rec.get("resumed") or 0) + 1, resumed_at=now, resume=rec["stage"])
    deploy_switch.save(path, rec)
    target = Path(rec.get("release") or rec.get("previous") or paths.home())
    try:
        how = spawn(path, target if target.is_dir() else paths.home())
    except (DeployError, OSError, subprocess.SubprocessError) as exc:
        rec.pop("resumed_at", None)
        rec.pop("resume", None)
        deploy_switch.save(path, rec)
        return f"starting it again failed: {exc}"
    print(f"deploy {row['id']}: the switch died at {rec.get('stage')}; resumed by {how}", file=sys.stderr)
    return ""


def settle(conn=None, now: float | None = None, alive=job_procs.alive, spawn=None, start=None) -> list[dict]:
    """Close every unfinished deploy of this machine whose job or switch has ended; a deploy job is never left running."""
    from harness import deploy_repair
    now = time.time() if now is None else now
    spawn = spawn or respawn
    # Before the store is opened: a deploy that died after migrating leaves it ahead of this code. #1752.
    done = recover(now, alive, spawn)
    settled = []
    try:
        with wq._store(conn) as c:
            where, args = wq._here(c)
            for row in c.execute(f"SELECT * FROM deploys WHERE outcome = '' AND {where} ORDER BY id", args).fetchall():
                try:
                    got = _settle_one(c, dict(row), now, alive, spawn)
                except ds.IllegalMove as exc:
                    print(f"deploy settle: {exc}", file=sys.stderr)
                    continue
                if got:
                    settled.append(got)
            claimed, cargs = wq._claimed(c)
            for job in c.execute(f"SELECT id FROM jobs WHERE kind = ? AND state = ? AND {claimed} AND id NOT IN "
                                 "(SELECT job_id FROM deploys WHERE job_id IS NOT NULL)", (KIND, wq.RUNNING, *cargs)):
                if job_procs._pid_of(job["id"]) is None and not job_claim.starting(job["id"]):
                    _close_job(c, job["id"], wq.FAILED, None, "interrupted before it recorded a deploy", now)
                    settled.append({"job": wq.label(job["id"]), "outcome": INTERRUPTED})
    except RuntimeError as exc:
        from harness import store_ahead
        if store_ahead.newer(exc) is None:
            raise
        # The linked release's worker cannot open a store a deploy left ahead of it: recover() was all it could do.
        print(f"deploy settle: {exc}", file=sys.stderr)
        return done + deploy_repair.auto(now, alive, start)
    # After the store pass, so a restore never runs under it. #1879.
    return settled + deploy_repair.auto(now, alive, start)


def _close_job(c, job_id, state: str, rc, note: str, now: float) -> None:
    why = js.INTERRUPTED if rc is None else js.DEPLOYED if state == wq.DONE else js.DEPLOY_FAILED
    js.move(c, job_id, wq.RUNNING, state, why, note[:2000], finished_at=now, **({} if rc is None else {"rc": rc}))
    c.commit()


def _hold_inputs(c, rec: dict, path: Path) -> None:
    """What the failed audit checks read after the rollback, so the poll can tell a retry would read the same. #1805."""
    from harness import deploy_hold
    try:
        rec["held_inputs"] = deploy_hold.inputs(c, rec["audit_failed"])
        deploy_switch.save(path, rec)
    except Exception as exc:  # noqa: BLE001 - no fingerprint only means the sha is retried as before
        print(f"deploy settle: no audit fingerprint for deploy {rec.get('id')}: {exc}", file=sys.stderr)


def _settle_one(c, row: dict, now: float, alive, spawn=None) -> dict | None:
    rec = _read(record_path(row["id"]))
    job = wq.get(row["job_id"], conn=c) if row["job_id"] is not None else None
    got = ds.outcome_of(rec)
    if got:
        if not move(c, row["id"], row["stage"], got, ds.SETTLE, detail=rec.get("detail", "")[:2000],
                    finished_at=rec.get("finished_at") or now, rolled_back_from=rec.get("rolled_back_from", ""),
                    **{k: rec[k] for k in ("release", "previous", "backup") if rec.get(k)}):
            return None
        if got == ROLLED_BACK and rec.get("audit_failed"):
            _hold_inputs(c, rec, record_path(row["id"]))
        from harness import cuts
        for t in rec.get("timed_out") or []:
            site_knob = t["site"]
            cuts.cut(site_knob, t["what"], kept=0, dropped=1, conn=c)
        if job is not None:
            ok = got == DEPLOYED
            _close_job(c, job["id"], wq.DONE if ok else wq.FAILED, 0 if ok else None if got == INTERRUPTED else 1,
                       f"deploy {row['id']} {got}: {rec.get('detail', '')}", now)
        return {"deploy": row["id"], "outcome": got}
    if rec:
        if _running(rec, now, alive):
            return None
        failed = ""
        if rec.get("stage") in ds.SWITCH_STAGES:
            if int(rec.get("resumed") or 0) < RESUMES:
                failed = _resume(rec, row, now, spawn or respawn)
                if not failed:
                    return None
            else:
                from harness import cuts
                cuts.cut("harness/deploy.py:RESUMES", f"deploy {row['id']} resume", kept=0, dropped=1, conn=c)
            from harness import deploy_repair
            got = deploy_repair.ahead(rec)
            if got is not None:
                deploy_repair.strand(rec, record_path(row["id"]), got, f"the switch died at {rec['stage']}"
                                     + (f" and {failed}" if failed else " with no restart left"), now)
                return _settle_one(c, row, now, alive, spawn)
        seen = view({**row, **{k: rec[k] for k in ("release", "previous") if rec.get(k)}}, rec, Path(rec["link"]))
        why = "; ".join(filter(None, (f"the switch stopped at {rec.get('stage')} without an outcome", failed, said(seen))))
        _lift(rec)
    else:
        if job is not None and job["state"] == wq.RUNNING and (job_procs._pid_of(job["id"]) is not None
                                                               or job_claim.starting(job["id"])):
            return None
        if job is not None and job["state"] != wq.RUNNING:
            why = f"job {job['id']} ended {job['state']} rc={job['rc']} before it recorded an outcome"
        else:
            why = "the job stopped before it handed off the switch"
        if row["stage"] == ds.MIGRATING:
            why += f"; the store may be part-migrated, its backup is {row['backup'] or 'not named'}"
    if not move(c, row["id"], row["stage"], INTERRUPTED, ds.SETTLE, detail=why[:2000], finished_at=now):
        return None
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


def _same(a: str, b) -> bool:
    return bool(a and b) and os.path.realpath(a) == os.path.realpath(str(b))


def view(row: dict, rec: dict | None = None, link: Path | None = None) -> dict:
    """The one reconciling read of a deploy: its stage (the switch record's while it switches) against what the link serves."""
    rec = _read(record_path(row["id"])) if rec is None else rec
    stage = row["stage"]
    if not row.get("outcome") and rec.get("stage"):
        stage = ds.outcome_of(rec) or rec["stage"]
    target = os.path.realpath(link) if link is not None and (Path(link).is_symlink() or Path(link).exists()) else ""
    serves = (ds.NONE if not target else ds.RELEASE if _same(target, row.get("release"))
              else ds.PREVIOUS if _same(target, row.get("previous")) else ds.OTHER)
    return {"deploy": row["id"], "stage": stage, "serves": serves, "path": target, "expect": ds.EXPECT.get(stage, ""),
            "state": ds.reconcile(stage, serves)}


_SERVES = {ds.RELEASE: "this deploy's release", ds.PREVIOUS: "the release before it", ds.OTHER: "another release"}


def said(v: dict) -> str:
    if v["serves"] == ds.NONE:
        return "no deploy link serves anything"
    out = f"the deploy link serves {_SERVES[v['serves']]} {v['path']}"
    if v["state"] == ds.SPLIT:
        out = f"{ds.SPLIT.upper()}: {v['stage']} says {_SERVES[v['expect']]} serves, but {out}"
    return out


def line(d: dict) -> str:
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["started_at"]))
    v = d.get("view")
    out = d["outcome"] or f"running ({v['stage'] if v else d['stage']})"
    back = f" from {d['rolled_back_from'][:12]} to {d['previous_sha'][:12]}" if d.get("rolled_back_from") else ""
    return (f"deploy {d['id']} {d['sha'][:12]} {when}: {out}{back}" + (f"; {said(v)}" if v else "")
            + (f"; {d['detail']}" if d.get("detail") else ""))


def serving(conn, link: Path | None = None) -> dict | None:
    """This machine's newest deploy reconciled against the deploy link; None before its first deploy."""
    where, args = wq._here(conn)
    row = conn.execute(f"SELECT * FROM deploys WHERE {where} ORDER BY id DESC", args).fetchone()
    return view(dict(row), link=link) if row else None


def status(conn) -> dict:
    link = paths.deploy_link()
    now = serving(conn, link)
    recent_ = recent(conn)
    for d in recent_:
        if now is not None and d["id"] == now["deploy"]:
            d["view"] = now
    return {"paused": paused(), "blocked": blocked(), "link": str(link) if link else "",
            "serving": str(link.resolve()) if link else "", "head": head_of(link) if link else "",
            "deploy": now, "recent": recent_, "jobs": [j for j in wq.jobs(conn) if j["kind"] == KIND][-5:]}
