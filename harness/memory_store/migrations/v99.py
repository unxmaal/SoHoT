"""Schema 99: watchdog_actions result, notified, job_id, pgid, run_dir, read once from each earlier row's text. #1778."""
from __future__ import annotations

import json
import os
import re

from harness.memory_store.migrations import columns as cols

VERSION = 99

_REFUSED = ("refused", "kept ", "not filed: LH_WATCHDOG_FILE", "not filed: privacy")
_UNAVAILABLE = ("notify unavailable", "pause unavailable", "nothing idle to unload")
NOTIFIED = "notified"


def columns(conn) -> None:
    cols._add_watchdog_result(conn)


def _result(outcome: str, dry_run: bool) -> str:
    """The result code an earlier row's outcome sentence stood for."""
    if dry_run:
        return "dry_run"
    if outcome.startswith("notify held"):
        return "held"
    if outcome.startswith(_REFUSED):
        return "refused"
    if outcome.startswith(_UNAVAILABLE):
        return "unavailable"
    if outcome.startswith("not filed") or " failed" in outcome.split(":")[0] or "still waiting" in outcome:
        return "failed"
    return "acted"


def _fields(row) -> tuple:
    """(result, notified, job_id, pgid, run_dir) for one earlier row."""
    outcome = row["outcome"] or ""
    try:
        ev = json.loads(row["evidence"] or "{}")
    except ValueError:
        ev = {}
    ev = ev if isinstance(ev, dict) else {}
    job = re.fullmatch(r"job (\d+)", row["subject"] or "")
    pgid = ev.get("pgid")
    out = re.search(r"--out[= ](\S+)", str(ev.get("command") or ""))
    run_dir = os.path.realpath(out.group(1)) if out and os.path.isabs(out.group(1)) else ""
    return (_result(outcome, bool(row["dry_run"])), int(f"{NOTIFIED}:" in outcome), int(job.group(1)) if job else None,
            int(pgid) if isinstance(pgid, int) or str(pgid).isdigit() else None, run_dir)


def data(conn) -> None:
    rows = conn.execute("SELECT id, subject, dry_run, outcome, evidence FROM watchdog_actions WHERE result = ''").fetchall()
    for r in rows:
        conn.execute("UPDATE watchdog_actions SET result = ?, notified = ?, job_id = ?, pgid = ?, run_dir = ? "
                     "WHERE id = ?", (*_fields(r), r["id"]))
