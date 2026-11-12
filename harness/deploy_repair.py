"""A deploy that ended with the store ahead of the code: which repair what was verified allows, and doing it (#1841)."""
from __future__ import annotations

import contextlib
import os
import time
import traceback
from pathlib import Path

from harness import deploy, deploy_switch, paths
from harness import deploy_state as ds
from harness import workqueue as wq

#: Put the pre-migrate copy back under the previous release; link the release that speaks the store; or neither verified.
RESTORE, FORWARD, OWNER = "restore", "forward", "owner"


def schemas(rec: dict) -> dict | None:
    """{'store', 'previous'} when the deploy migrated and the store is still past the schema the previous release speaks."""
    if not rec.get("migrated"):
        return None
    previous = rec.get("previous") or ""
    speaks = wq.code_schema(previous) if previous and Path(previous).is_dir() else None
    speaks = rec.get("schema_from") if speaks is None else speaks
    if speaks is None:
        return None
    have = deploy._schema_now(Path(rec.get("db") or paths.home() / "discovery.db"))
    return {"store": have, "previous": int(speaks)} if have > int(speaks) else None


def ahead(rec: dict) -> dict | None:
    """schemas() for a switch that stopped short of verifying its release; None for any other record."""
    if rec.get("stage") not in ds.SWITCH_STAGES or rec["stage"] == ds.VERIFIED:
        return None
    return schemas(rec)


def _backup_unverified(rec: dict, speaks: int) -> str:
    """'' when the pre-migrate copy is there at the schema the previous release speaks, else why not."""
    from harness import store
    named = rec.get("backup") or ""
    if not named:
        return "the deploy named no pre-migrate copy"
    p = Path(named)
    if not p.is_file() or p.stat().st_size == 0:
        return f"the pre-migrate copy {named} is missing or empty"
    try:
        if store.backend() == store.POSTGRES:
            from harness import store_service
            # A pg_dump taken before the migration: its table of contents must read; its schema is the one it was taken at.
            store_service.verify(p)
            return ""
        conn = store.open_ro(p)
        try:
            have = deploy._store_schema(conn)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - an unreadable copy is one that does not verify, and says why
        return f"the pre-migrate copy {named} cannot be read ({deploy_switch.named(exc)})"
    if have != speaks:
        return f"the pre-migrate copy {named} is at schema {have}, not the {speaks} the previous release speaks"
    return ""


def _release_unverified(rec: dict, have: int) -> str:
    release = rec.get("release") or ""
    if not release or not Path(release).is_dir():
        return f"the release {release or '(none named)'} is gone"
    speaks = wq.code_schema(release)
    if speaks != have:
        return f"the release {release} speaks schema {speaks}, not the store's {have}"
    return ""


def plan(rec: dict, got: dict) -> tuple[str, str]:
    """(RESTORE|FORWARD|OWNER, the repair in words): the copy if it verifies, else the release if it speaks the store."""
    no_copy = _backup_unverified(rec, got["previous"])
    if not no_copy:
        return RESTORE, (f"restore the pre-migrate copy {rec['backup']} (verified at schema {got['previous']}), "
                         f"link and reinstall the previous release {rec['previous']}")
    no_release = _release_unverified(rec, got["store"])
    if not no_release:
        return FORWARD, (f"{no_copy}, so flip forward: link the release {rec['release']} (it speaks schema "
                         f"{got['store']}), reinstall and verify it")
    return OWNER, f"{no_copy} and {no_release}, so no repair is verified: put the store and the deploy link right by hand"


def strand(rec: dict, path: Path, got: dict, why: str, now: float) -> dict:
    """End the record STORE_AHEAD with its planned repair, said in words and alerted; the queue pause stays."""
    how, words = plan(rec, got)
    act = f"repair: {words}: soh deploy repair {rec.get('id', path.stem)}" if how != OWNER else f"repair: {words}"
    text = (f"STORE AHEAD: {why}; the store is at schema {got['store']} and the previous release speaks "
            f"{got['previous']}; {act}; the queue stays paused until then")
    rec.update(repair=how, repair_plan=words, stage=ds.STORE_AHEAD, outcome=ds.STORE_AHEAD, detail=text[:2000],
               finished_at=now)
    deploy_switch.save(path, rec)
    deploy._alert_here(f"deploy {rec.get('id', path.stem)} of {str(rec.get('sha', ''))[:12]} {text}")
    return {"deploy": rec.get("id", path.stem), "outcome": ds.STORE_AHEAD, "detail": text}


def pending() -> list[dict]:
    """Deploys that ended STORE_AHEAD and are not repaired yet, read from their records alone (no store)."""
    d = paths.home() / "deploys"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json"), key=lambda p: (len(p.stem), p.stem)):
        rec = deploy._read(p)
        if ds.outcome_of(rec) == ds.STORE_AHEAD and not rec.get("repaired"):
            out.append({"deploy": rec.get("id", p.stem), "sha": str(rec.get("sha", "")), "repair": rec.get("repair", ""),
                        "detail": rec.get("detail", "")})
    return out


def lines(waiting: list[dict]) -> list[str]:
    return [f"deploy {w['deploy']} of {w['sha'][:12]} needs a repair: {w['detail']}" for w in waiting]


@contextlib.contextmanager
def _install_env(rec: dict):
    """The environment the owner's install recorded, as the switch's steps get it (#1518); restored after."""
    got = deploy_switch.read_install_env(rec["install_env"]) if rec.get("install_env") else {}
    before = {k: os.environ.get(k) for k in got}
    os.environ.update(got)
    try:
        yield
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _restore(rec: dict, got: dict | None, log, end: float) -> str:
    deploy_switch.flip(Path(rec["link"]), Path(rec["previous"]))
    if got is not None:
        schema = deploy_switch.restore(Path(rec["backup"]), Path(rec["db"]))
        if schema != got["previous"]:
            return f"the restore left the store at schema {schema}, not the previous release's {got['previous']}"
        log.write(f"--- store restored from {rec['backup']} (schema {schema})\n")
    bad = deploy_switch._step(rec, rec["rollback_install"], rec["previous"], deploy_switch.INSTALL_TIMEOUT_S, log,
                              "reinstall of the previous release", end=end,
                              site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S")
    if bad or not rec.get("verify"):
        return bad
    deploy_switch._repair(rec, rec["release"], log, end)
    return deploy_switch._step(rec, rec["verify"][0], rec["previous"], deploy_switch.VERIFY_TIMEOUT_S, log,
                               "smoke of the previous release", end=end,
                               site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S")


def _forward(rec: dict, log, end: float) -> str:
    deploy_switch.flip(Path(rec["link"]), Path(rec["release"]))
    bad = deploy_switch._step(rec, rec["install"], rec["release"], deploy_switch.INSTALL_TIMEOUT_S, log,
                              "reinstall of the release", end=end,
                              site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S")
    if bad:
        return bad
    deploy_switch._repair(rec, rec["release"], log, end)
    for argv in rec.get("verify") or []:
        bad = deploy_switch._step(rec, argv, rec["release"], deploy_switch.VERIFY_TIMEOUT_S, log,
                                  " ".join(map(str, argv[-2:])), end=end,
                                  site_knob="harness/deploy_switch.py:VERIFY_TIMEOUT_S")
        if bad:
            return bad
    return ""


def repair(deploy_id) -> dict:
    """Do the planned repair of a STORE_AHEAD deploy, planned again on what verifies now; {'ok', 'how', 'detail'}."""
    path = deploy.record_path(deploy_id)
    rec = deploy._read(path)
    if ds.outcome_of(rec) != ds.STORE_AHEAD:
        return {"ok": False, "how": "", "detail": f"deploy {deploy_id} waits on no repair: its outcome is "
                                                  f"{rec.get('outcome') or 'not recorded'}"}
    if rec.get("repaired"):
        return {"ok": False, "how": rec["repaired"].get("how", ""),
                "detail": f"deploy {deploy_id} is already repaired: {rec['repaired'].get('detail', '')}"}
    got = schemas(rec)
    how, words = plan(rec, got) if got else (RESTORE, "the store is back at the previous release's schema, so link "
                                                      "and reinstall that release")
    if how == OWNER:
        return {"ok": False, "how": how, "detail": words}
    with open(rec.get("log") or paths.logs() / "deploy.log", "a", encoding="utf-8") as log, _install_env(rec):
        log.write(f"=== repair of deploy {deploy_id} {time.strftime('%Y-%m-%dT%H:%M:%S')}: {how}: {words}\n")
        end = time.monotonic() + deploy_switch.SWITCH_DEADLINE_S
        try:
            bad = _restore(rec, got, log, end) if how == RESTORE else _forward(rec, log, end)
        except Exception as exc:  # noqa: BLE001 - whatever stopped the repair is said, and the queue stays paused
            log.write(traceback.format_exc())
            bad = f"the {how} repair failed: {deploy_switch.named(exc)}"
        if bad:
            rec.setdefault("repair_failed", []).append({"at": time.time(), "how": how, "why": bad})
            deploy_switch.save(path, rec)
            log.write(f"--- repair failed: {bad}\n")
            return {"ok": False, "how": how, "detail": f"{bad}; the queue stays paused"}
        lifted = deploy._lift(rec)
        said = "; ".join(filter(None, (words, lifted)))
        rec["repaired"] = {"at": time.time(), "how": how, "detail": said}
        deploy_switch.save(path, rec)
        log.write(f"--- repaired: {said}\n")
    return {"ok": True, "how": how, "detail": said}
