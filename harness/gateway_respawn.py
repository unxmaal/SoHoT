"""A gateway switch the worker started again, marked until it claims its row, so one that dies first is settled. #1904."""
from __future__ import annotations

import json
import time
from pathlib import Path

from harness import stale_temp
from harness import atomic_file

CLAIM_S = 300.0
FILE = "gateway-switch.respawn"
_KEYS = ("requested_at", "after", "spawned_at", "pid", "pgid", "started")


def path() -> Path:
    from harness import paths
    return paths.home() / FILE


#: An earlier row settled unclaimed for the same process as row r: r is that respawn's late claim. #1940.
_LATE = ("FROM gateway_switch_runs u WHERE u.reason = ? AND u.pid = r.pid AND u.started = r.started "
         "AND u.started <> '' AND u.id < r.id")


def newest(conn) -> int:
    """The newest gateway_switch_runs id but a late claim's, 0 with none: a respawn has claimed once a row is newer than its mark's."""
    from harness import gateway_switch_state as st
    return int(conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM gateway_switch_runs r WHERE NOT EXISTS (SELECT 1 {_LATE})",
                            (st.UNCLAIMED,)).fetchone()[0])


def late(conn, rid: int) -> int | None:
    """The switch that settled this claim's process unclaimed, so switch rid must not run; None for any other claim. #1940."""
    from harness import gateway_switch_state as st
    row = conn.execute(f"SELECT (SELECT MIN(u.id) {_LATE}) FROM gateway_switch_runs r WHERE r.id = ?",
                       (st.UNCLAIMED, int(rid))).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def mark(requested_at: float, after: int, spawned_at: float, pid: int | None = None) -> None:
    """Record a respawn: before its process starts (pid None), then again with the process's identity."""
    from harness import proc_identity
    ident = proc_identity.identity(pid) if pid else {"pid": None, "pgid": None, "started": ""}
    to = path()
    tmp = stale_temp.temp(to, "{name}.{pid}.{thread}")
    tmp.write_text(json.dumps({"requested_at": requested_at, "after": int(after), "spawned_at": spawned_at,
                               **ident}), encoding="utf-8")
    atomic_file.replace(tmp, to)


def read() -> dict | None:
    """The respawn mark; None with none, {} when it cannot be read."""
    try:
        rec = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) and all(k in rec for k in _KEYS) else {}


def clear() -> None:
    path().unlink(missing_ok=True)


def unclaimed(conn, now: float | None = None, same=None, log=None) -> dict | None:
    """Settle a respawned switch that never claimed its row: died once its process is gone, unclaimed past CLAIM_S; the settled row, else None."""
    from harness import cuts, gateway, proc_identity
    from harness import gateway_switch_state as st
    rec = read()
    if rec is None:
        return None
    if not rec:
        clear()
        if log:
            log(f"an unreadable respawn mark at {path()} was removed")
        return None
    now = time.time() if now is None else now
    gone = (same or proc_identity.same)(rec) is False
    if newest(conn) > int(rec["after"]):
        clear()
        return None
    waited = now - float(rec["spawned_at"])
    if not gone and waited < CLAIM_S:
        return None
    try:
        rid = st.claim(conn, now=now, requested_at=rec["requested_at"], config=str(gateway.served_path()),
                       pid=rec["pid"], pgid=rec["pgid"], started=rec["started"])
    except st.Lost:
        clear()
        return None
    why = "died" if gone else f"had not claimed it {waited:.0f} s after it was started (gateway_respawn_claim)"
    st.move(conn, rid, st.REQUESTED, st.FAILED, st.DIED if gone else st.UNCLAIMED, now=now,
            detail=f"the switch the worker started again {why} before it claimed its row"
                   + ("" if gone else "; a claim it makes later is refused"))
    clear()
    if not gone:
        cuts.cut("gateway_respawn_claim",f"switch {rid} settled unclaimed", kept=0, dropped=1, conn=conn)
    return st.get(conn, rid)
