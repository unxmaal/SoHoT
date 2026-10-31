"""`soh sweep-check`: is tonight's discovery sweep running and progressing, read from launchd and the loop heartbeat. #1062."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, time as dtime, timedelta

RUNNING, STALLED, EXITED, FINISHED, EARLY, NEVER, UNLOADED, UNKNOWN, UNSUPPORTED = (
    "running", "stalled", "exited", "finished", "finished_early", "never_started", "not_loaded", "unknown",
    "unsupported")
#: Verdicts a healthy night gives; every other one notifies, once per change.
QUIET = (RUNNING, FINISHED, UNSUPPORTED)
CRITERION = "sweep_check"
SUBJECT = "discover sweep"
SERVICE = "discover"
#: No heartbeat progress this long, or the current step's declared deadline when longer, reads as stalled.
STALL_S = 3600.0
#: A sweep that finished rc 0 this soon after it started finished early.
EARLY_S = 1800.0
#: A loop started this long before the scheduled hour still counts as tonight's.
START_SLACK_S = 900.0
PROBE_TIMEOUT_S = 10.0
NOTIFY_TITLE = "SoHoT sweep check"
_FIELD = re.compile(r"^\t(state|pid|runs|last exit code|last terminating signal) = (.*)$")


def parse_launchctl(text: str) -> dict:
    """The top-level state, pid, runs, last exit code and signal of one `launchctl print` service."""
    got: dict = {}
    for line in (text or "").splitlines():
        m = _FIELD.match(line)
        if m:
            got.setdefault(m.group(1), m.group(2).strip())
    code = got.get("last exit code", "")
    return {"loaded": True, "state": got.get("state", ""),
            "pid": int(got["pid"]) if got.get("pid", "").isdigit() else None,
            "runs": int(got["runs"]) if got.get("runs", "").isdigit() else None,
            "rc": int(code) if re.fullmatch(r"-?\d+", code) else None,
            "signal": got.get("last terminating signal", "")}


def launchd(service: str = SERVICE, run=subprocess.run, platform: str | None = None,
            uid: int | None = None) -> dict | None:
    """The discover unit as launchd sees it; None where there is no launchd."""
    if (platform or sys.platform) != "darwin":
        return None
    getuid = getattr(os, "getuid", None)
    if uid is None and getuid is None:
        return {"loaded": None, "why": f"no user id to name the launchd domain with on {sys.platform}"}
    from harness import volume
    try:
        got = run(["launchctl", "print", f"gui/{getuid() if uid is None else uid}/{volume.PREFIX}.{service}"],
                  capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"loaded": None, "why": f"launchctl could not be asked: {exc}"}
    if got.returncode != 0:
        return {"loaded": False, "why": (got.stderr or got.stdout or "").strip()[:200]}
    return parse_launchctl(got.stdout)


def tonight(now: float, hours) -> float:
    """When the most recent scheduled discover start at or before `now` was."""
    at = datetime.fromtimestamp(now)
    starts = [datetime.combine(at.date() - timedelta(days=back), dtime(int(h) % 24)).timestamp()
              for back in (0, 1) for h in hours or [21]]
    return max(t for t in starts if t <= now)


def _hm(t) -> str:
    return datetime.fromtimestamp(float(t)).strftime("%H:%M")


def verdict(unit: dict | None, beat: dict | None, now: float, start: float, alive=None) -> dict:
    """{verdict, line}: what tonight's sweep is doing, from the launchd unit and the loop heartbeat."""
    from harness import heartbeat
    alive = alive or heartbeat.alive
    if unit is None:
        return {"verdict": UNSUPPORTED, "line": f"not supported here: the sweep check reads launchd, which "
                                               f"{sys.platform} does not have"}
    if unit.get("loaded") is None:
        return {"verdict": UNKNOWN, "line": unit.get("why") or "launchctl could not be asked"}
    if unit.get("loaded") is False:
        return {"verdict": UNLOADED, "line": f"the discover unit is not loaded in launchd "
                                            f"({unit.get('why') or 'no such service'}); scripts/launchd.sh install loads it"}
    from harness import cuts
    b = beat if beat and float(beat.get("started") or 0) >= start - START_SLACK_S else None
    if beat and b is None:
        cuts.cut("sweep_check_start_slack", "a heartbeat that started before tonight's window")
    live = unit.get("state") == "running" and bool(unit.get("pid"))
    rc = unit.get("rc")
    sig = f", {unit['signal']}" if unit.get("signal") else ""
    told = f"launchd: {unit.get('state') or 'no state'}, runs {unit.get('runs')}, last exit code " \
           f"{'never exited' if rc is None else rc}{sig}"
    if b is None:
        if live:
            return {"verdict": STALLED, "line": f"launchd runs the discover unit (pid {unit['pid']}) but its loop "
                                               f"has written no heartbeat since the {_hm(start)} start"}
        return {"verdict": NEVER, "line": f"no discovery sweep has started since {_hm(start)} ({told})"}
    where = heartbeat._where(b)
    ran = float(b.get("finished") or b.get("updated") or now) - float(b["started"])
    if b.get("state") == heartbeat.FINISHED:
        if b.get("rc") != 0:
            how = f"rc {b['rc']}" if b.get("rc") is not None else f"error: {b.get('error') or 'none recorded'}"
            return {"verdict": EXITED, "line": f"the sweep exited {how} at {_hm(b.get('finished') or now)} after "
                                              f"{heartbeat.ago(ran)}, at {where}"}
        short = int(b.get("step") or 0) < int(b.get("total") or 0)
        if ran < EARLY_S or short:
            if not short:
                cuts.cut("sweep_check_early", "a finished sweep read as finished early")
            return {"verdict": EARLY, "line": f"the sweep finished rc 0 after only {heartbeat.ago(ran)} at "
                                             f"{_hm(b.get('finished') or now)}, at {where}"}
        return {"verdict": FINISHED, "line": f"the sweep finished rc 0 at {_hm(b.get('finished') or now)} after "
                                            f"{heartbeat.ago(ran)}"}
    pid = int(b.get("pid") or 0)
    if not alive(pid):
        return {"verdict": EXITED, "line": f"the sweep's loop (pid {pid}) died without finishing, at {where} "
                                          f"({told})"}
    # A loop waiting behind a holder that still beats is not stalled. #775.
    age = now - heartbeat.progress_at(b)
    limit = max(STALL_S, float(b.get("deadline_s") or 0))
    outside = "" if live else f" (pid {pid}, not under the launchd unit)"
    if age > limit:
        if limit == STALL_S:
            cuts.cut("sweep_check_stall", "a running sweep read as stalled")
        return {"verdict": STALLED, "line": f"the sweep is stalled{outside}: no progress for {heartbeat.ago(age)} "
                                           f"(limit {heartbeat.ago(limit)}), at {where}"}
    return {"verdict": RUNNING, "line": f"the sweep is running{outside}: {where}; last progress "
                                       f"{heartbeat.ago(age)} ago"}


def check(now: float | None = None, unit=None, beat=None, hours=None, alive=None) -> dict:
    """One reading: launchd, heartbeat, tonight's start and the verdict; every read injectable."""
    import time

    from harness import heartbeat
    now = time.time() if now is None else now
    unit = launchd() if unit is None else unit
    beat = heartbeat.read() if beat is None else beat
    start = tonight(now, heartbeat.discover_hours() if hours is None else hours)
    got = verdict(unit, beat, now, start, alive=alive)
    keep = ("state", "pid", "started", "updated", "finished", "rc", "error", "tier", "step", "total", "candidate")
    return {**got, "at": now, "start": start, "launchd": unit,
            "heartbeat": {k: (beat or {}).get(k) for k in keep} if beat else None}


def _machine(conn):
    from harness import watchdog
    return watchdog._machine(conn)


def previous(conn, start: float) -> str:
    """The verdict the last recorded check of tonight's sweep gave, '' when none."""
    m = _machine(conn)
    row = conn.execute(
        "SELECT evidence FROM watchdog_actions WHERE criterion = ? AND at >= ? "
        "AND (machine_id = ? OR (machine_id IS NULL AND ? IS NULL)) ORDER BY at DESC, id DESC LIMIT 1",
        (CRITERION, start - START_SLACK_S, m, m)).fetchone()
    try:
        return str(json.loads(row["evidence"] or "{}").get("verdict") or "") if row else ""
    except ValueError:
        return ""


def should_notify(r: dict, before: str) -> bool:
    """Only a verdict that is not healthy, and only when it changed since the last check of this sweep."""
    return r["verdict"] not in QUIET and r["verdict"] != before


def record(conn, r: dict, notify=None) -> dict:
    """Store the check as a watchdog_actions row, notifying through the watchdog path first when it should."""
    from harness import watchdog
    before = previous(conn, r["start"])
    send = should_notify(r, before)
    if send:
        outcome = (notify or watchdog.desktop)(NOTIFY_TITLE, r["line"], f"discover sweep: {r['verdict']}")
    elif r["verdict"] in QUIET:
        outcome = f"noted: {r['line']}"
    else:
        outcome = f"notify held: the last check already said {before}; {r['line']}"
    evidence = {k: r[k] for k in ("verdict", "line", "start", "launchd", "heartbeat")}
    cur = conn.execute(
        "INSERT INTO watchdog_actions (at, machine_id, criterion, subject, action, escalated, dry_run, "
        "evidence, outcome) VALUES (?,?,?,?,?,?,?,?,?)",
        (r["at"], _machine(conn), CRITERION, SUBJECT, watchdog.NOTIFY if send else watchdog.NOTE, 0, 0,
         json.dumps(evidence, default=str, sort_keys=True), outcome))
    conn.commit()
    return {"row": cur.lastrowid, "notified": send, "outcome": outcome, "previous": before}


def rows(conn, since: float) -> list[dict]:
    """Every recorded check since `since`, oldest first, for soh morning."""
    out = []
    for r in conn.execute("SELECT id, at, action, evidence, outcome FROM watchdog_actions WHERE criterion = ? "
                          "AND at >= ? ORDER BY at, id", (CRITERION, since)):
        try:
            ev = json.loads(r["evidence"] or "{}")
        except ValueError:
            ev = {}
        out.append({"id": r["id"], "at": r["at"], "verdict": ev.get("verdict", ""), "line": ev.get("line", ""),
                    "notified": r["action"] == "notify", "outcome": r["outcome"]})
    return out
