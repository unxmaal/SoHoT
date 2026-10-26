"""`soh floors [derive|plant]`: pass thresholds against a known-good instrument's noise floor, read-only (#730)."""
from __future__ import annotations

import shlex
import sqlite3
from pathlib import Path

from harness import floors
from harness.commands.common import emit, err, note


def _derive(a, refs=None, prompts=None, cases=None) -> int:
    from harness import live_audit
    from harness import memory_store as ms
    db = Path(getattr(a, "store", "") or ms.db_path())
    if not db.is_file():
        return err(f"floors: no store at {db}")
    try:
        conn = live_audit.open_readonly(db)
    except (OSError, sqlite3.Error) as exc:
        return err(f"floors: {exc}")
    try:
        rows = floors.report(conn, refs=refs, prompts=prompts, cases=cases,
                             share=getattr(a, "share", None), min_items=getattr(a, "min_items", None))
    finally:
        conn.close()
    for r in rows:
        mark = "ok " if r["agrees"] else "OFF"
        note(f"{mark} {r['knob']}: default {r['current']}, {r['status']}, floor {r.get('floor', '-')} -> "
             f"{r['derived']}, n {r['n']} ({r['instrument']})")
    good = all(r["agrees"] for r in rows)
    emit(good, floors=rows)
    return 0 if good else 1


def _plant(a) -> int:
    out = Path(a.out)
    written = floors.plant(out)
    note(f"{len(written)} clean ocr cases under {out}; queue each night run from the deploy checkout:")
    for argv in floors.night(out.resolve()):
        note(f"  soh jobs --title 'floors #730' add --night -- {shlex.join(argv)}")
    emit(True, cases=len(written), night=floors.night(out.resolve()))
    return 0


def cmd_floors(a, refs=None, prompts=None, cases=None) -> int:
    try:
        if getattr(a, "action", "derive") == "plant":
            return _plant(a)
        return _derive(a, refs, prompts, cases)
    except (OSError, ValueError) as exc:
        return err(f"floors: {exc}")
