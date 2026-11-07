"""`soh store`, `soh memory` and `soh disk`: the store, the memory ceiling and the weights on disk."""
from __future__ import annotations

from pathlib import Path
import json

from harness.commands.common import emit, err, note
from harness.commands import common


def _pg_env():
    """PG* from the environment when set, else the container on this machine as its owner."""
    import os
    from harness import store, store_service as svc
    if os.environ.get("PGHOST") or store.marker():
        return None
    return {**os.environ, **svc.owner_environ()}


def _postgres(a) -> int:
    """The Postgres actions of `soh store`: the container, the copy each way, the switch. #1507."""
    import time
    from harness import memory_store as ms, paths, store, store_copy, store_service as svc
    if a.action in ("pg-up", "pg-down", "pg-status"):
        verb = {"pg-up": ["up", "-d", "--wait"], "pg-down": ["stop"], "pg-status": ["ps", "--format", "json"]}
        got = svc.compose(verb[a.action])
        note((got.stdout or "") + (got.stderr or ""))
        emit(ok=got.returncode == 0, rc=got.returncode)
        return 0 if got.returncode == 0 else 1
    if a.action == "pg-roles":
        conn = store.postgres_connect(svc.owner_environ())
        try:
            svc.grant_reader(conn, store.DEFAULT_READER, svc.password(store.DEFAULT_READER, ensure=True))
        finally:
            conn.close()
        note(f"read-only role {store.DEFAULT_READER} can connect and SELECT; its password is in the Keychain")
        emit(ok=True, reader=store.DEFAULT_READER)
        return 0
    if a.action == "switch":
        got = svc.switch(a.to, dry_run=a.dry_run)
        note(json.dumps(got, indent=1, sort_keys=True))
        emit(**got)
        return 0
    if a.action == "migrate-to-postgres":
        db = Path(a.path) if a.path else ms.db_path()
        if not db.is_file():
            return err(f"no SQLite store at {db}")
        snap = Path(a.snapshot) if a.snapshot else (
            paths.home() / "backups" / f"sqlite-to-postgres-{time.strftime('%Y%m%d-%H%M%S')}.db")
        got = store_copy.to_postgres_report(db, snap, dry_run=a.dry_run, replace=a.replace, environ=_pg_env())
    else:
        if not a.path:
            return err("export-to-sqlite needs the NEW file to write, e.g. ~/localharness/discovery-from-pg.db")
        got = store_copy.to_sqlite_report(Path(a.path), environ=_pg_env())
    for row in got.get("verify", []):
        note(f"{'ok  ' if row['ok'] else 'DIFF'} {row['table']:<28} {row['rows']:>9} rows  {row['digest'][:16]}"
             f"{'' if row['ok'] else '  ' + row['why']}")
    for k in ("why", "gaps", "occupied", "rows", "foreign_key_violations", "snapshot", "dest"):
        if got.get(k):
            note(f"{k}: {got[k]}")
    emit(**got)
    return 0 if got["ok"] else 1


def cmd_store(a) -> int:
    """Migrate a copy of a store with this checkout and check it. #478."""
    import sqlite3

    if a.action != "dry-run":
        return _postgres(a)
    from harness import migration_check as mc
    try:
        got = mc.dry_run(Path(a.path) if a.path else None, keep=a.keep)
    except (OSError, sqlite3.Error) as exc:
        return err(f"dry run failed: {exc}")
    note(mc.report_text(got))
    emit(ok=got["ok"], **{k: v for k, v in got.items() if k != "ok"})
    return 0 if got["ok"] else 1


def cmd_audit(a) -> int:
    """The store's invariants and what the gateway serves, on the live store, read-only. #492."""
    import sqlite3

    from harness import live_audit
    try:
        got = live_audit.audit(Path(a.path) if a.path else None)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        return err(f"audit failed: {exc}")
    note(live_audit.report_text(got))
    emit(ok=got["ok"], **{k: v for k, v in got.items() if k != "ok"})
    return 0 if got["ok"] else 1


def cmd_memory(a) -> int:
    """How far this machine's memory goes before macOS pushes back. #299."""
    from harness import memory_store as ms, ramp

    if a.action == "show":
        store = ms.connect()
        try:
            limits = {r["fingerprint"]: ramp.runs(store, r["id"]) for r in
                      store.execute("SELECT DISTINCT m.id, m.fingerprint "
                                    "FROM memory_limits l JOIN machines m "
                                    "ON m.id = l.machine_id").fetchall()}
        finally:
            store.close()
        if not limits:
            return err("nothing measured yet: soh memory ramp records one")
        note(json.dumps(limits, indent=1, sort_keys=True))
        emit(limits=limits)
        return 0
    note(f"allocating {a.step_gb:g} GB at a time until macOS first warns; "
         f"everything is freed at the end", flush=True)
    from harness import exclusive
    try:
        with exclusive.held("ramp", announce=lambda m: note(m, flush=True)):
            got = ramp.run(step_gb=a.step_gb, settle_s=a.settle,
                           floor_pct=a.floor_pct, cap_gb=a.cap_gb)
    except ValueError as exc:
        return err(str(exc))
    if not got["steps"]:
        return err(f"nothing was allocated ({got['stopped']}), so there is "
                   f"nothing to record")
    for s in got["steps"]:
        note(f"  {s['gb']:5.1f} GB  level {s['level']}  free {s['free_pct']}%  "
             f"available {s['available_gb']:.1f} GB  wired {s['wired_gb']}  "
             f"swapouts {s['swapouts']}", flush=True)
    note(f"\nstopped: {got['stopped']}; last step at normal pressure: "
         f"{got['last_normal_gb']:g} GB on top of what was already running")
    if got["margin_gb"] is not None:
        note(f"margin: macOS warned {got['margin_gb']:.1f} GB short of the "
             f"guard's own available figure; the guard now reserves "
             f"the largest margin measured on this machine")
    store = ms.connect()
    try:
        mid = ms.remember_machine(store)
        ramp.save(store, got, mid)
    finally:
        store.close()
    note(f"recorded for machine {mid} in the store")
    emit(machine_id=mid, report=got)
    return 0


def cmd_disk(a) -> int:
    """What the weights cache holds and what may go. #370, #373."""
    if getattr(a, "action", "") == "speed":
        from harness.commands.volume import cmd_disk_speed
        return cmd_disk_speed(a)
    import time as _time

    from harness import disk, memory_store as ms
    now = _time.time()
    try:
        conn = ms.connect()
    except Exception as exc:  # noqa: BLE001
        note(f"no discovery store ({exc}); deletion disabled")
        conn = None
    try:
        if getattr(a, "record", False):
            if conn is None:
                return err("no discovery store; nothing to record into")
            from harness import downloads
            got = downloads.record_unrecorded(conn)
            note(f"recorded {got['recorded']} path(s) with no row, stamped "
                 f"{got['gone']} gone row(s) removed")
        inv = disk.inventory(conn)
        if not a.delete:
            note(disk.table(inv, now))
            emit(**disk.as_json(inv, now))
            return 0
        doomed = disk.plan(inv, now, a.delete)
        size = sum(e.size for e in doomed)
        for e in doomed:
            note(f"  {disk.gib(e.size):>7} GiB  {e.name}  ({e.why})")
        if not inv.complete:
            return err("refusing to delete: " + "; ".join(inv.problems))
        if not doomed:
            note(f"nothing in {a.delete} is safe to delete")
            emit(removed=[], bytes=0)
            return 0
        if not a.yes:
            if common._JSON:
                return err(f"--json needs --yes to delete {len(doomed)} "
                           f"entries ({disk.gib(size)} GiB)")
            try:
                answer = input(f"delete {len(doomed)} entries, "
                               f"{disk.gib(size)} GiB? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                note("nothing deleted")
                return 1
        removed = disk.delete(inv, now, a.delete, conn)
    finally:
        if conn is not None:
            conn.close()
    ok = [r for r in removed if "error" not in r]
    freed = sum(r["bytes"] for r in ok)
    for r in removed:
        if "error" in r:
            note(f"  not removed: {r['path']}: {r['error']}")
    note(f"removed {len(ok)}, freed {disk.gib(freed)} GiB")
    emit(ok=len(ok) == len(removed), removed=removed, bytes=freed)
    return 0 if len(ok) == len(removed) else 1
