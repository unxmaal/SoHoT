"""The one-shot step of a queue deploy that switches releases, verifies, and rolls back; it outlives the worker it restarts. #1506.

A deploy job writes a record and hands this file to launchd (or a detached process), then exits. This runs
as a file with `python3 -I`, so it loads nothing outside the stdlib but harness from its own release root.
Its only output is the record, saved after every stage; the worker settles the job from it.
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
import traceback
from pathlib import Path

if __name__ == "__main__":
    # Run as a file under -I: harness is importable only from this file's own release root. #1610.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from harness import deploy_state as ds  # noqa: E402 - after the release root joins sys.path
from harness import proc_identity  # noqa: E402
from harness import stale_temp  # noqa: E402
from harness.atomic_file import replace  # noqa: E402

#: How long the new release's `launchd.sh reinstall` may take: the worker quiesce, deferred periodic units, preflight and the audit.
INSTALL_TIMEOUT_S = 3600.0
#: The line quiesce.cli says when a job outlived the worker quiesce: the install failed for it. #1762.
NOT_QUIESCED = "not-quiesced"
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
DEPLOYED, ROLLED_BACK, FAILED, FAILED_FORWARD = ds.DEPLOYED, ds.ROLLED_BACK, ds.FAILED, ds.FAILED_FORWARD
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
    replace(tmp, path)


def env(base=None) -> dict:
    base = os.environ if base is None else base
    return {k: v for k, v in base.items() if k not in DROP_ENV}


def flip(link: Path, target: Path) -> None:
    """Point the deploy link at target in one rename, so no reader sees it missing."""
    link, target = Path(link), Path(target)
    tmp = stale_temp.temp(link, ".{name}.{pid}")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp)
    replace(tmp, link)


def restore(backup: Path, db: Path) -> int:
    """Copy the pre-migration backup over the live store (SQLite's backup API, or pg_restore); the schema it holds."""
    from harness import store
    if store.backend() == store.POSTGRES:
        from harness import store_service
        store_service.restore(Path(backup))
        return store_service.schema()
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


def named(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _keep(rec: dict, stage: str, path) -> None:
    ds.check(rec.get("stage", ds.NEW), stage, ds.SWITCH)
    rec["stage"] = stage
    if path is not None:
        save(path, rec)


def _repair(rec: dict, cwd: str, log, end: float) -> None:
    """Set non-model GGUFs aside and restart the router before a smoke; a failure is logged, the smoke still judges. #1674."""
    if not rec.get("repair"):
        return
    why = _step(rec, rec["repair"], cwd, VERIFY_TIMEOUT_S, log, "repair",
                site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S", end=end)
    rec.setdefault("repaired", []).append(why or "done")
    log.write(f"--- repair before smoke: {why or 'done'}\n")


def _size(log) -> int | None:
    try:
        log.flush()
        return os.fstat(log.fileno()).st_size
    except (OSError, ValueError, AttributeError):
        return None


def _audited(rec: dict, log, start: int | None, why: str) -> str:
    """why; the audit checks the failed step's output names as FAIL go in rec['audit_failed'] for the poll. #1805."""
    if start is not None:
        try:
            from harness import deploy_hold  # only on a failed step: the switch starts on the stdlib and deploy_state
            log.flush()
            with open(log.name, "rb") as f:
                f.seek(start)
                text = f.read().decode("utf-8", "replace")
            got = deploy_hold.failed(text)
        except (OSError, ValueError, AttributeError, ImportError):
            got, text = {}, ""
        if got:
            rec["audit_failed"] = got
        held = [line for line in text.splitlines() if line.startswith(f"{NOT_QUIESCED}: ")]
        if held:
            why = f"{why}: {held[-1]}"
    return why


def forward(rec: dict, log, end: float, path=None) -> str:
    """Switch to the new release, reinstall its units, verify; '' when it all passed by `end` (monotonic)."""
    flip(Path(rec["link"]), Path(rec["release"]))
    rec["switched_at"] = time.time()
    _keep(rec, ds.FLIPPED, path)
    start = _size(log)
    why = _step(rec, rec["install"], rec["release"], INSTALL_TIMEOUT_S, log, "install",
                site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S", end=end)
    if why:
        return _audited(rec, log, start, why)
    _keep(rec, ds.INSTALLED, path)
    _repair(rec, rec["release"], log, end)
    for argv in rec["verify"]:
        start = _size(log)
        why = _step(rec, argv, rec["release"], VERIFY_TIMEOUT_S, log, " ".join(map(str, argv[-2:])),
                    site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S", end=end)
        if why:
            return _audited(rec, log, start, why)
    _keep(rec, ds.VERIFIED, path)
    return ""


#: Stages a rollback has reached; a resumed rollback goes on from the one recorded. #1753.
_BACK = (ds.ROLLING_BACK, ds.FLIPPED_BACK, ds.RESTORED, ds.RESTORE_FAILED, ds.ROLLBACK_INSTALLED, ds.ROLLBACK_VERIFIED)


def rollback(rec: dict, why: str, log, end: float, path=None) -> str:
    """Back to the previous release, the store backup if a migration ran, its units; what the rollback itself found."""
    if rec.get("stage") not in _BACK:
        rec["rollback_why"] = why
        _keep(rec, ds.ROLLING_BACK, path)
    said = []
    if rec["stage"] == ds.ROLLING_BACK:
        flip(Path(rec["link"]), Path(rec["previous"]))
        _keep(rec, ds.FLIPPED_BACK, path)
    if rec["stage"] == ds.RESTORE_FAILED:
        flip(Path(rec["link"]), Path(rec["release"]))
        return (f"the store restore had FAILED ({rec.get('restore_failed', '')}); the link is back on "
                f"{rec['release']} and its units stay")
    if rec["stage"] == ds.FLIPPED_BACK and rec.get("migrated") and rec.get("backup"):
        try:
            said.append(f"store restored from {rec['backup']} (schema {restore(Path(rec['backup']), Path(rec['db']))})")
        except Exception as exc:  # noqa: BLE001 - any failure leaves the store on the new schema, handled below
            # The previous release refuses the newer store, so the new release keeps the link and its units.
            flip(Path(rec["link"]), Path(rec["release"]))
            rec["restore_failed"] = named(exc)
            _keep(rec, ds.RESTORE_FAILED, path)
            return (f"store restore from {rec['backup']} FAILED ({named(exc)}); the store keeps the new schema, so "
                    f"the link is back on {rec['release']} and its units stay")
        _keep(rec, ds.RESTORED, path)
    bad = ""
    if rec["stage"] in (ds.FLIPPED_BACK, ds.RESTORED):
        bad = _step(rec, rec["rollback_install"], rec["previous"], INSTALL_TIMEOUT_S, log, "rollback install",
                    site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S", end=end)
        said.append(bad or "previous release reinstalled")
        _keep(rec, ds.ROLLBACK_INSTALLED, path)
    if rec["stage"] == ds.ROLLBACK_INSTALLED and not bad and rec["verify"]:
        # The new release's verb: the previous one may predate it, and the files it moves stay moved. #1674.
        _repair(rec, rec["release"], log, end)
        bad = _step(rec, rec["verify"][0], rec["previous"], VERIFY_TIMEOUT_S, log, "smoke after rollback",
                    site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S", end=end)
        said.append(bad or "smoke passed after rollback")
        _keep(rec, ds.ROLLBACK_VERIFIED, path)
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


def _resumed(rec: dict, died: str) -> str:
    """'' when a dead switch had verified its release, else why its rollback runs or goes on."""
    if died == ds.VERIFIED:
        return ""
    if died in _BACK:
        return f"{rec.get('rollback_why') or 'the switch was rolling back'}; the switch died at {died} and was resumed"
    return f"the switch died at {died} and was resumed to roll back"


def _end(rec: dict) -> None:
    """The outcome becomes the stage; one MOVES does not list from where the switch stopped ends failed, never unrecorded."""
    try:
        ds.check(rec["stage"], rec["outcome"], ds.SWITCH)
    except ds.IllegalMove as exc:
        rec.update(outcome=FAILED, detail=f"{rec['detail']}; {exc}")
    rec.update(stage=rec["outcome"], finished_at=time.time())


def switch(path: Path) -> dict:
    path = Path(path)
    rec = load(path)
    # Launchd gave this process no shell profile; every step runs in what the owner's install recorded. #1518.
    os.environ.update(read_install_env(rec["install_env"]) if rec.get("install_env") else {})
    # The record handed to the switch is the hand-off; settle hands a dead switch back with `resume` naming its stage. #1753.
    rec.setdefault("stage", ds.HANDED_OFF)
    died = rec.pop("resume", "")
    if died and (died != rec["stage"] or died not in ds.SWITCH_STAGES or rec.get("outcome")):
        raise ds.IllegalMove(f"deploy: settle handed a resume at {died}, but the record is at {rec['stage']}")
    # Its pid with group and start time: a pid alone is reused after a reboot. #1773.
    me = proc_identity.identity(os.getpid())
    rec.update(pid=me["pid"], identity=me, switch_started=time.time())
    if died:
        save(path, rec)
    else:
        _keep(rec, ds.SWITCHING, path)
    Path(rec["log"]).parent.mkdir(parents=True, exist_ok=True)
    with open(rec["log"], "a", encoding="utf-8") as log:
        try:
            if died:
                log.write(f"--- resuming deploy {rec.get('id', '')}: the switch died at {died}\n")
                why = _resumed(rec, died)
            else:
                why = forward(rec, log, time.monotonic() + SWITCH_DEADLINE_S, path)
        except Exception as exc:  # noqa: BLE001 - whatever stopped the switch, it rolls back and says why
            log.write(traceback.format_exc())
            why = f"switch failed: {named(exc)}"
        if not why:
            rec.update(outcome=DEPLOYED, detail=f"{rec['sha'][:12]} serving from {rec['release']}")
        else:
            try:
                done = rollback(rec, why, log, time.monotonic() + SWITCH_DEADLINE_S, path)
                if rec.get("restore_failed"):
                    rec.update(outcome=FAILED_FORWARD, detail=f"{why}; the rollback could not restore the store, so "
                                                              f"{rec['sha'][:12]} still serves: {done}")
                else:
                    rec.update(outcome=ROLLED_BACK, rolled_back_from=rec["sha"],
                               detail=f"{why}; rolled back to {rec.get('previous_sha', '')[:12]}: {done}")
            except Exception as exc:  # noqa: BLE001 - a rollback that raises still ends in a recorded outcome
                log.write(traceback.format_exc())
                rec.update(outcome=FAILED, detail=f"{why}; the rollback itself failed at {rec['stage']}: {named(exc)}")
            head = "this machine is broken, not the release: " if rec.get("environment_broken") else ""
            alert(rec, f"{head}deploy of {rec['sha'][:12]} {rec['outcome']}: {rec['detail']}", log)
        if not rec.get("queue_was_paused"):
            Path(rec["queue_flag"]).unlink(missing_ok=True)
        _end(rec)
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
