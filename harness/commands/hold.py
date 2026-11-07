"""`soh hold benchmarks|gpu|release|status|let`: the owner's hold, one per scope. #1564, #1509, #1508."""
from __future__ import annotations

import re

from harness.commands.common import emit, err, note


def _until(spec: str) -> float | None:
    import time

    from harness import workqueue as wq
    spec = (spec or "").strip()
    if not spec:
        return None
    return wq.at_date(spec, time.time()) if re.match(r"\d{4}-", spec) else wq.at_clock(spec, time.time())


def _status(conn) -> int:
    from harness import hold
    got = hold.actives(conn)
    for h in got:
        note(f"{hold.line(h)}. While held, {hold.SCOPES[h['kind']]}.")
    if not got:
        note("no hold: benchmarking and GPU jobs run as usual")
    emit(hold=got[0] if len(got) == 1 else None, holds=got)
    return 0


def cmd_hold(a) -> int:
    from harness import hold
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        if a.action in hold.SCOPES:
            try:
                got = hold.hold(conn, " ".join(a.said), until=_until(a.until), scope=a.action)
            except ValueError as exc:
                return err(str(exc))
            note(f"{hold.line(got)}. While held, {hold.SCOPES[a.action]}.")
            emit(hold=got)
            return 0
        if a.action == "release":
            if len(a.said) > 1 or (a.said and a.said[0] not in hold.SCOPES):
                return err(f"release takes one scope: {hold.RELEASE} {'|'.join(hold.SCOPES)}")
            try:
                got = hold.release(conn, scope=a.said[0] if a.said else None)
            except ValueError as exc:
                return err(str(exc))
            note(f"{hold.line(got)}; what it held may start" if got else "no such hold is in force")
            emit(hold=got)
            return 0
        if a.action == "let":
            if len(a.said) != 1:
                return err("let needs one job id: soh hold let 0241")
            try:
                hold.let(conn, a.said[0])
            except ValueError as exc:
                return err(str(exc))
            note(f"job {a.said[0]} may start through the benchmark hold")
            emit(job=a.said[0], despite_hold=True)
            return 0
        return _status(conn)
    finally:
        conn.close()
