"""The one-shot step of a queue deploy that switches releases, verifies, and rolls back; it outlives the worker it restarts. #1506.

A deploy job writes a record and hands this file to launchd (or a detached process), then exits. This runs
as a file with `python3 -I`, so it imports nothing outside the stdlib and no release's code can change under
it. Its only output is the record; the worker settles the job and the deploys row from it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

#: How long the new release's `launchd.sh reinstall` may take: the worker quiesce, deferred periodic units, preflight and the audit.
INSTALL_TIMEOUT_S = 3600.0
#: How long one verify command (smoke, then soh coherence) may take on the live system.
VERIFY_TIMEOUT_S = 1800.0
#: How long the alert script may take.
ALERT_TIMEOUT_S = 120.0
#: Variables a deploy run must not hand to the release's scripts: they would pin the old checkout or its venv.
DROP_ENV = ("LH_DEPLOY", "LH_REPO", "LH_REEXECED", "LH_GPU_LOCK_HELD", "VIRTUAL_ENV", "LH_JOB_ID")
DEPLOYED, ROLLED_BACK, FAILED = "deployed", "rolled_back", "failed"


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
    """Copy the pre-migration backup over the live store through SQLite's backup API; the schema it holds."""
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
    try:
        got = subprocess.run([str(a) for a in argv], cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                             env={**env(), **(extra or {})}, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:.0f} s"
    except OSError as exc:
        return None, f"could not run: {exc}"
    return got.returncode, ""


def _step(rec: dict, argv: list, cwd: str, timeout: float, log, what: str, *, site_knob: str) -> str:
    """'' when argv exited 0, else why; a timeout is noted in rec['timed_out'] for the worker's cut."""
    rc, why = run(argv, cwd, timeout, log)
    if rc == 0:
        return ""
    if why.startswith("timed out"):
        rec.setdefault("timed_out", []).append({"site": site_knob, "what": what})
    return f"{what} {why or f'exited rc {rc}'}"


def forward(rec: dict, log) -> str:
    """Switch to the new release, reinstall its units, verify; '' when it all passed."""
    flip(Path(rec["link"]), Path(rec["release"]))
    rec["switched_at"] = time.time()
    why = _step(rec, rec["install"], rec["release"], INSTALL_TIMEOUT_S, log, "install",
                site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S")
    if why:
        return why
    for argv in rec["verify"]:
        why = _step(rec, argv, rec["release"], VERIFY_TIMEOUT_S, log, " ".join(map(str, argv[-2:])),
                    site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S")
        if why:
            return why
    return ""


def rollback(rec: dict, why: str, log) -> str:
    """Back to the previous release, the store backup if a migration ran, its units; what the rollback itself found."""
    flip(Path(rec["link"]), Path(rec["previous"]))
    said = []
    if rec.get("migrated") and rec.get("backup"):
        try:
            said.append(f"store restored from {rec['backup']} (schema {restore(Path(rec['backup']), Path(rec['db']))})")
        except (OSError, sqlite3.Error, ValueError) as exc:
            said.append(f"store restore FAILED: {exc}")
    bad = _step(rec, rec["rollback_install"], rec["previous"], INSTALL_TIMEOUT_S, log, "rollback install",
                site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S")
    said.append(bad or "previous release reinstalled")
    if not bad and rec["verify"]:
        bad = _step(rec, rec["verify"][0], rec["previous"], VERIFY_TIMEOUT_S, log, "smoke after rollback",
                    site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S")
        said.append(bad or "smoke passed after rollback")
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
    rec.update(stage="switching", pid=os.getpid(), switch_started=time.time())
    save(path, rec)
    Path(rec["log"]).parent.mkdir(parents=True, exist_ok=True)
    with open(rec["log"], "a", encoding="utf-8") as log:
        try:
            why = forward(rec, log)
        except OSError as exc:
            why = f"switch failed: {exc}"
        if not why:
            rec.update(outcome=DEPLOYED, detail=f"{rec['sha'][:12]} serving from {rec['release']}")
        else:
            try:
                done = rollback(rec, why, log)
                rec.update(outcome=ROLLED_BACK, rolled_back_from=rec["sha"],
                           detail=f"{why}; rolled back to {rec.get('previous_sha', '')[:12]}: {done}")
            except OSError as exc:
                rec.update(outcome=FAILED, detail=f"{why}; the rollback itself failed: {exc}")
            alert(rec, f"deploy of {rec['sha'][:12]} {rec['outcome']}: {rec['detail']}", log)
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
    rec = switch(Path(argv[0]))
    return 0 if rec["outcome"] == DEPLOYED else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
