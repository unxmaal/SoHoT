"""`soh gguf-aux`: list the drafters, MTP heads and shards in the router's GGUF dir; --apply sets them aside. #1674."""
from __future__ import annotations

from harness import gguf
from harness.commands.common import emit, err, note


def cmd_gguf_aux(a) -> int:
    found = gguf.auxiliaries()
    where = gguf.quarantine_dir()
    for path, why in found:
        note(f"  {path.name}: {why}")
    if not a.apply:
        note(f"{len(found)} auxiliary GGUF(s) in {gguf.models_dir()}"
             + (f"; --apply moves them to {where} and restarts the router" if found else ""))
        emit(True, files=[{"path": str(p), "why": why} for p, why in found], moved=[])
        return 0
    moved = []
    for path, why in found:
        try:
            moved.append({"path": str(path), "why": why, "to": str(gguf.set_aside(path, where))})
        except OSError as exc:
            return err(f"gguf-aux: {path.name} not moved: {exc}; moved so far: {[m['path'] for m in moved]}")
    _stamp(moved)
    why = gguf.refresh_router() if moved else ""
    note(f"moved {len(moved)} auxiliary GGUF(s) to {where}; nothing deleted"
         + (f"; router restart: {why}" if why else "; the router restarted" if moved else ""))
    emit(not why, files=[{"path": m["path"], "why": m["why"]} for m in moved], moved=moved, restart=why)
    return 1 if why else 0


def _stamp(moved) -> None:
    """The moved files' downloads rows marked removed, so no plan or fetch counts them as served."""
    if not moved:
        return
    from harness import downloads
    from harness import memory_store as ms
    try:
        conn = ms.connect()
    except Exception as exc:  # noqa: BLE001 - a deploy runs this beside a store on another schema; the files moved anyway
        note(f"downloads rows not stamped ({exc}); the next downloads scan finds the files absent")
        return
    try:
        for m in moved:
            if downloads.live(conn, path=m["path"]):
                downloads.removed(conn, m["path"], by=f"gguf-aux: {m['why']}")
    finally:
        conn.close()
