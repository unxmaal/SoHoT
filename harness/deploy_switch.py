"""The one-shot step of a queue deploy that switches releases, verifies, and rolls back; it outlives the worker it restarts. #1506.

A deploy job writes a record and hands this file to launchd (or a detached process), then exits. This runs
as a file with `python3 -I`, so it imports nothing outside the stdlib and no release's code can change under
it. Its only output is the record; the worker settles the job and the deploys row from it.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

#: How long the new release's `launchd.sh reinstall` may take: the worker quiesce, deferred periodic units, preflight and the audit.
INSTALL_TIMEOUT_S = 3600.0
#: How long one verify command (smoke, then soh coherence) may take on the live system.
VERIFY_TIMEOUT_S = 1800.0
#: How long the switch (reinstall, then verify) may take in all before it rolls back and alerts; the rollback gets as long again. #1515.
SWITCH_DEADLINE_S = 3600.0
#: How long a step's killed process group has to exit before the switch stops waiting for it.
REAP_TIMEOUT_S = 30.0
#: How long the alert script may take.
ALERT_TIMEOUT_S = 120.0
#: Variables a deploy run must not hand to the release's scripts: they would pin the old checkout or its venv.
DROP_ENV = ("LH_DEPLOY", "LH_REPO", "LH_REEXECED", "LH_GPU_LOCK_HELD", "VIRTUAL_ENV", "LH_JOB_ID", "SMOKE_PHASE")
DEPLOYED, ROLLED_BACK, FAILED = "deployed", "rolled_back", "failed"
#: Every switch step runs after the switch, so scripts/smoke-introduced.sh enforces (#1608).
SMOKE_PHASE_ENV = "SMOKE_PHASE"
#: The file under the harness home where scripts/launchd.sh install records the environment it read. #1518.
INSTALL_ENV = "install.env"


def read_install_env(path) -> dict:
    """KEY=VALUE lines of the install record; {} when it is missing."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key and key not in out:
            out[key] = value
    return out


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: Path, rec: dict) -> None:
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def env(base=None) -> dict:
    base = os.environ if base is None else base
    return {k: v for k, v in base.items() if k not in DROP_ENV}


def flip(link: Path, target: Path) -> None:
    """Point the deploy link at target in one rename, so no reader sees it missing."""
    link, target = Path(link), Path(target)
    tmp = link.with_name(f".{link.name}.{os.getpid()}")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, link)


def restore(backup: Path, db: Path) -> int:
    """Copy the pre-migration backup over the live store (SQLite's backup API, or pg_restore); the schema it holds."""
    from harness import store
    if store.backend() == store.POSTGRES:
        from harness import store_service
        from harness.memory_store import connection
        store_service.restore(Path(backup))
        conn = store.postgres_connect()
        try:
            return connection._pg_schema(conn)
        finally:
            conn.close()
    src = sqlite3.connect(f"file:{Path(backup)}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(db), timeout=60)
        try:
            src.backup(dst)
            row = dst.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        finally:
            dst.close()
    finally:
        src.close()
    return int(row[0]) if row else 0


def run(argv: list, cwd: str, timeout: float, log, extra=None) -> tuple[int | None, str]:
    """(rc, '') or (None, why) when it could not run or ran out of time."""
    log.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} in {cwd}: {' '.join(map(str, argv))}\n")
    log.flush()
    _TERM["held"] = True
    try:
        child = subprocess.Popen([str(a) for a in argv], cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                 env={**env(), SMOKE_PHASE_ENV: "after", **(extra or {})}, start_new_session=sys.platform != "win32")
    except OSError as exc:
        _release_term()
        return None, f"could not run: {exc}"
    try:
        _release_term()
        return child.wait(timeout=timeout), ""
    except subprocess.TimeoutExpired:
        _kill(child)
        return None, f"timed out after {timeout:.0f} s"
    except BaseException:
        _kill(child)
        raise


#: A TERM that lands while a step spawns waits until the step's handle is inside the try that kills it (RULE #916).
_TERM = {"held": False, "pending": None}


def _on_term(sig, _frame) -> None:
    if _TERM["held"]:
        _TERM["pending"] = sig
        return
    raise SystemExit(128 + sig)


def _release_term() -> None:
    _TERM["held"] = False
    if _TERM["pending"] is not None:
        raise SystemExit(128 + _TERM["pending"])


def _kill(child) -> None:
    """Kill the step and everything it started, so nothing it left behind keeps the machine lock."""
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            child.kill()
        else:
            os.killpg(child.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        child.wait(timeout=REAP_TIMEOUT_S)


def _step(rec: dict, argv: list, cwd: str, timeout: float, log, what: str, *, site_knob: str, end: float,
          deadline_knob: str = "harness/deploy_switch.py:SWITCH_DEADLINE_S") -> str:
    """'' when argv exited 0, else why; a timeout is noted in rec['timed_out'] for the worker's cut."""
    left = end - time.monotonic()
    if left < timeout:
        timeout, site_knob = max(0.0, left), deadline_knob
    rc, why = run(argv, cwd, timeout, log) if timeout > 0 else (None, "timed out after 0 s")
    if rc == 0:
        return ""
    if why.startswith("timed out"):
        rec.setdefault("timed_out", []).append({"site": site_knob, "what": what})
        if site_knob == deadline_knob:
            why = f"ran past the switch deadline of {SWITCH_DEADLINE_S:.0f} s"
    return f"{what} {why or f'exited rc {rc}'}"


def forward(rec: dict, log, end: float) -> str:
    """Switch to the new release, reinstall its units, verify; '' when it all passed by `end` (monotonic)."""
    flip(Path(rec["link"]), Path(rec["release"]))
    rec["switched_at"] = time.time()
    why = _step(rec, rec["install"], rec["release"], INSTALL_TIMEOUT_S, log, "install",
                site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S", end=end)
    if why:
        return why
    for argv in rec["verify"]:
        why = _step(rec, argv, rec["release"], VERIFY_TIMEOUT_S, log, " ".join(map(str, argv[-2:])),
                    site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S", end=end)
        if why:
            return why
    return ""


def rollback(rec: dict, why: str, log, end: float) -> str:
    """Back to the previous release, the store backup if a migration ran, its units; what the rollback itself found."""
    flip(Path(rec["link"]), Path(rec["previous"]))
    said = []
    if rec.get("migrated") and rec.get("backup"):
        try:
            said.append(f"store restored from {rec['backup']} (schema {restore(Path(rec['backup']), Path(rec['db']))})")
        except (OSError, sqlite3.Error, ValueError) as exc:
            said.append(f"store restore FAILED: {exc}")
    bad = _step(rec, rec["rollback_install"], rec["previous"], INSTALL_TIMEOUT_S, log, "rollback install",
                site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S", end=end)
    said.append(bad or "previous release reinstalled")
    if not bad and rec["verify"]:
        bad = _step(rec, rec["verify"][0], rec["previous"], VERIFY_TIMEOUT_S, log, "smoke after rollback",
                    site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S", end=end)
        said.append(bad or "smoke passed after rollback")
        if bad:
            rec["environment_broken"] = True
            said.append(f"the previous release fails too, so this machine is broken, not release {rec['sha'][:12]}")
    return "; ".join(said)


def alert(rec: dict, message: str, log) -> None:
    extra = {"MONIT_SERVICE": "deploy", "MONIT_EVENT": rec.get("outcome", ""), "MONIT_DESCRIPTION": message}
    log.write(f"--- alert: {message}\n")
    try:
        subprocess.run([str(a) for a in rec["alert"]], cwd=rec["previous"], stdout=log, stderr=subprocess.STDOUT,
                       env={**env(), **extra}, timeout=ALERT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        log.write(f"alert did not run: {exc}\n")


def switch(path: Path) -> dict:
    path = Path(path)
    rec = load(path)
    # Launchd gave this process no shell profile; every step runs in what the owner's install recorded. #1518.
    os.environ.update(read_install_env(rec["install_env"]) if rec.get("install_env") else {})
    rec.update(stage="switching", pid=os.getpid(), switch_started=time.time())
    save(path, rec)
    Path(rec["log"]).parent.mkdir(parents=True, exist_ok=True)
    with open(rec["log"], "a", encoding="utf-8") as log:
        try:
            why = forward(rec, log, time.monotonic() + SWITCH_DEADLINE_S)
        except OSError as exc:
            why = f"switch failed: {exc}"
        if not why:
            rec.update(outcome=DEPLOYED, detail=f"{rec['sha'][:12]} serving from {rec['release']}")
        else:
            try:
                done = rollback(rec, why, log, time.monotonic() + SWITCH_DEADLINE_S)
                rec.update(outcome=ROLLED_BACK, rolled_back_from=rec["sha"],
                           detail=f"{why}; rolled back to {rec.get('previous_sha', '')[:12]}: {done}")
            except OSError as exc:
                rec.update(outcome=FAILED, detail=f"{why}; the rollback itself failed: {exc}")
            head = "this machine is broken, not the release: " if rec.get("environment_broken") else ""
            alert(rec, f"{head}deploy of {rec['sha'][:12]} {rec['outcome']}: {rec['detail']}", log)
        if not rec.get("queue_was_paused"):
            Path(rec["queue_flag"]).unlink(missing_ok=True)
        rec.update(stage=rec["outcome"], finished_at=time.time())
        save(path, rec)
        log.write(f"--- {rec['outcome']}: {rec['detail']}\n")
    return rec


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: deploy_switch.py RECORD", file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, _on_term)
    rec = switch(Path(argv[0]))
    return 0 if rec["outcome"] == DEPLOYED else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
