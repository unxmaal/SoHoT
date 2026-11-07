"""`soh gate status|hold|release`: the contention gate GPU jobs and deploys wait for, and the owner's hold. #1509."""
from __future__ import annotations

import time

from harness.commands.common import emit, err, note


def _line(h: dict) -> str:
    until = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["until"])) if h.get("until") else "a release"
    return f"held: {h['said']}, until {until}"


def cmd_gate(a) -> int:
    from harness import contention
    from harness import memory_store as ms
    from harness import workqueue as wq
    if a.action == "hold":
        try:
            got = contention.hold(" ".join(a.said), wq.start_at(a.until) if a.until else None)
        except ValueError as exc:
            return err(str(exc))
        note(f"{_line(got)}; no GPU job or deploy starts, and the watchdog pauses a running one at its next case")
        emit(hold=got)
        return 0
    if a.action == "release":
        got = contention.release()
        note(f"released the hold: {got['said']}" if got else "no hold was in force")
        emit(hold=got)
        return 0
    conn = ms.connect()
    try:
        v = contention.verdict(conn)
    finally:
        conn.close()
    note(f"contention gate {'open' if v['open'] else 'closed'}: {v['why']}")
    note(f"  memory pressure level {v['pressure_level']}; {v['served']} client request(s) in the last "
         f"{v['idle_s']:.0f} s (contention_idle){': ' + str(v['by_alias']) if v['by_alias'] else ''}")
    if v["hold"]:
        note(f"  {_line(v['hold'])}")
    emit(**v)
    return 0
