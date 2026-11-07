"""`soh hold benchmarks|release|status|let`: the owner's hold on discovery sweeps, reverifies and measurement jobs. #1564."""
from __future__ import annotations

import re

from harness.commands.common import emit, err, note

#: What a hold stops, said wherever it is shown.
STOPS = ("the discover loop starts no sweep, reverify and knob sweeps queue nothing, and the queue starts no "
         "evals.run, adopt, reverify or discover job; deploys, serving and other jobs still run. "
         "soh hold let JOB (or soh jobs add --despite-hold) lets one measurement job through")


def _until(spec: str) -> float | None:
    import time

    from harness import workqueue as wq
    spec = (spec or "").strip()
    if not spec:
        return None
    return wq.at_date(spec, time.time()) if re.match(r"\d{4}-", spec) else wq.at_clock(spec, time.time())


def cmd_hold(a) -> int:
    from harness import hold
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        if a.action == "benchmarks":
            try:
                got = hold.hold(conn, " ".join(a.said), until=_until(a.until))
            except ValueError as exc:
                return err(str(exc))
            note(f"{hold.line(got)}. While held, {STOPS}.")
            emit(hold=got)
            return 0
        if a.action == "release":
            got = hold.release(conn)
            note(f"{hold.line(got)}; held measurement jobs may start" if got else "no benchmark hold is in force")
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
        got = hold.active(conn)
        note(f"{hold.line(got)}. While held, {STOPS}." if got else "no benchmark hold: benchmarking runs as usual")
        emit(hold=got)
        return 0
    finally:
        conn.close()
