"""`soh day clear|status|revoke`: Eric's word that this machine may run jobs all day. #1112."""
from __future__ import annotations

from harness.commands.common import emit, err, note

#: What a clearance lifts, said wherever it is shown.
LIFTS = ("the watchdog's daytime_gpu and long_run day limit for every job, and the night start of jobs queued "
         "with --night; no_progress, orphan, memory, the night limits and --not-before HH:MM still apply")


def cmd_day(a) -> int:
    from harness import day_clear
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        if a.action == "clear":
            try:
                got = day_clear.clear(conn, " ".join(a.said))
            except ValueError as exc:
                return err(str(exc))
            note(f"{day_clear.line(got)}. Lifts {LIFTS}.")
            emit(clearance=got)
            return 0
        if a.action == "revoke":
            got = day_clear.revoke(conn)
            note(day_clear.line(got) if got else "no day clearance is in force")
            emit(clearance=got)
            return 0
        got = day_clear.active(conn)
        note(f"{day_clear.line(got)}. Lifts {LIFTS}." if got else
             "no day clearance: the watchdog's day limits and night starts apply")
        emit(clearance=got)
        return 0
    finally:
        conn.close()
