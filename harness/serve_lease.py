"""Serving preempts measurement: a delegation's lease, and the running evals that yield to it between cases. #1556."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

from harness import paths

#: Seconds a lease outlives a delegation's answer, so a follow-up call skips the model swap back. #1556.
GRACE_S = 120.0
#: Seconds a delegation waits for a running eval to reach a case boundary before it refuses. #1556.
WAIT_S = 300.0
#: Seconds between looks at the lease, or at an eval that has not yielded yet.
POLL_S = 0.5
#: A case this many times past its planned seconds is cut at once for a waiting delegation. #1556.
CUT_FACTOR = 2.0
#: Seconds a delegation waits for a case it asked to cut to end, past which it refuses. #1556.
CUT_WAIT_S = 30.0
#: The warm p95 a decide or extract delegation should answer in, wait included; the report flags a lane past it. #1556.
P95_TARGET_S = 10.0
#: Lanes held to P95_TARGET_S.
TARGET_LANES = ("decide", "extract")

WAITING, SERVING, IDLE = "waiting", "serving", "idle"
#: Yielder states: in a case, between cases, or yielded to a lease.
CASE, BETWEEN, YIELDED = "case", "between", "yielded"
#: serve_waits outcomes; beside answered while a case ran, so both timings are contended.
ANSWERED, REFUSED, BESIDE = "answered", "refused", "beside"


def _dir(name: str) -> Path:
    d = paths.home() / "serving" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _alive(pid) -> bool:
    from harness import workqueue
    try:
        return workqueue.alive(int(pid))
    except (TypeError, ValueError):
        return False


def _write(path: Path, record: dict) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:6]}")
    tmp.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _drop(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        # A file another process holds open on Windows; a later reader removes it.
        print(f"serve_lease: {path.name} left ({exc})", file=sys.stderr)


class Lease:
    """One delegation's claim on the machine: waiting, serving, then idle for GRACE_S after it answers."""

    def __init__(self, lane: str, holder: str, clock=time.time):
        self.clock = clock
        self.path = _dir("leases") / f"{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
        self.record = {"holder": holder, "lane": lane, "pid": os.getpid(), "since": clock()}
        self.set(WAITING)

    def set(self, state: str, until: float | None = None) -> None:
        self.record.update(state=state, until=until)
        _write(self.path, self.record)

    def serving(self) -> None:
        self.set(SERVING)

    def idle(self) -> None:
        self.set(IDLE, until=self.clock() + GRACE_S)

    def drop(self) -> None:
        _drop(self.path)


def holders(now: float | None = None) -> list[dict]:
    """The live leases: waiting or serving in a live process, or idle inside their grace; a lapsed one is removed."""
    now = time.time() if now is None else now
    out = []
    for f in sorted(_dir("leases").glob("*.json")):
        r = _read(f)
        state = r.get("state")
        live = (state in (WAITING, SERVING) and _alive(r.get("pid"))) or (
            state == IDLE and float(r.get("until") or 0) > now)
        if live:
            out.append(r)
        else:
            _drop(f)
    return out


def held(now: float | None = None) -> str:
    """Who holds the serving lease, or "" when nobody does."""
    got = holders(now)
    if not got:
        return ""
    first = got[0]
    more = f" and {len(got) - 1} more" if len(got) > 1 else ""
    return f"{first.get('holder') or 'a delegation'} (pid {first.get('pid')}, {first.get('state')}){more}"


class Yielder:
    """A running eval's record of where it is, so a delegation knows when it may load a model. #1556."""

    def __init__(self, out, clock=time.time):
        self.clock = clock
        self.path = _dir("yielders") / f"{os.getpid()}.json"
        self.record = {"pid": os.getpid(), "out": str(out or ""), "state": BETWEEN, "at": clock()}
        _write(self.path, self.record)

    def _set(self, **fields) -> None:
        self.record.update(at=self.clock(), **fields)
        _write(self.path, self.record)

    def case(self, candidate: str, case: str, planned_s) -> None:
        self._set(state=CASE, candidate=candidate, case=case, case_started=self.clock(), planned_s=planned_s)

    def between(self) -> None:
        self._set(state=BETWEEN)

    def yielding(self, to: str) -> None:
        self._set(state=YIELDED, to=to, since=self.clock())

    def cut_asked(self) -> bool:
        """Whether a delegation asked this eval to cut the case in flight."""
        return _cut_path(self.record["pid"]).exists()

    def cut_done(self) -> dict:
        """Take the cut request, the case it was for now ended; what it said."""
        path = _cut_path(self.record["pid"])
        got = _read(path)
        _drop(path)
        return got

    def contended(self) -> list[dict]:
        """The delegations answered beside this eval since it last asked, the file then cleared."""
        path = _beside_path(self.record["pid"])
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        _drop(path)
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def close(self) -> None:
        for path in (self.path, _cut_path(self.record["pid"]), _beside_path(self.record["pid"])):
            _drop(path)


def _cut_path(pid) -> Path:
    return _dir("cuts") / f"{pid}.json"


def _beside_path(pid) -> Path:
    return _dir("beside") / f"{pid}.jsonl"


def ask_cut(found: list[dict], why: str) -> list[int]:
    """Ask every eval in a case to cut it; the pids asked."""
    asked = []
    for r in found:
        if r.get("state") == CASE and r.get("pid"):
            _write(_cut_path(r["pid"]), {"at": time.time(), "why": why, "case": r.get("case", ""),
                                         "candidate": r.get("candidate", "")})
            asked.append(int(r["pid"]))
    return asked


def past_plan(found: list[dict], now: float | None = None) -> bool:
    """Whether a case in flight has run CUT_FACTOR times its planned seconds."""
    now = time.time() if now is None else now
    for r in found:
        plan = r.get("planned_s")
        if r.get("state") == CASE and plan and now - float(r.get("case_started") or now) > CUT_FACTOR * float(plan):
            return True
    return False


def mark_beside(found: list[dict], lane: str) -> int:
    """Note on every eval in a case that a delegation answers beside it; how many were in one."""
    n = 0
    for r in found:
        if r.get("state") == CASE and r.get("pid"):
            with _beside_path(r["pid"]).open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.time(), "lane": lane}) + "\n")
            n += 1
    return n


def yielders() -> list[dict]:
    """Every live eval that yields to a lease; a dead one's record is removed."""
    out = []
    for f in sorted(_dir("yielders").glob("*.json")):
        r = _read(f)
        if r and _alive(r.get("pid")):
            out.append(r)
        else:
            _drop(f)
    return out


def yielded(found: list[dict] | None = None) -> bool:
    """Whether some eval yields here and every one of them is between cases, waiting on the lease."""
    found = yielders() if found is None else found
    return bool(found) and all(r.get("state") == YIELDED for r in found)


def in_flight(found: list[dict], now: float | None = None) -> str:
    """The case a running eval is in, how long it has run and against what plan; "" when none is in one."""
    now = time.time() if now is None else now
    for r in found:
        if r.get("state") != CASE:
            continue
        ran = max(0.0, now - float(r.get("case_started") or now))
        plan = r.get("planned_s")
        over = (f" against a planned {float(plan):.0f}s" + (", past its plan" if ran > float(plan) else "")
                if plan else ", with no plan to compare")
        what = f"case {r['case']}" if r.get("case") else "warm-up"
        return f"its {what} of {r.get('candidate') or '?'} has run {ran:.0f}s{over}"
    return ""


def record_wait(lane: str, holder: str, waited_s: float, outcome: str, case: str = "", call_id: str = "",
                cut: bool = False) -> None:
    """A serve_waits row for a delegation that found the machine held; a store failure never fails the call."""
    try:
        from harness import memory_store as ms
        from harness import usage
        path = usage.target()
        if path is None:
            return
        conn = ms.connect(path)
        try:
            conn.execute("INSERT INTO serve_waits (at, lane, holder, waited_s, outcome, in_flight, call_id, cut) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (time.time(), lane, holder, round(float(waited_s), 3), outcome, case, call_id, int(cut)))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"serve_waits: not recorded ({exc})", file=sys.stderr)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 3)


def waits(conn, since: float, now: float | None = None) -> list[dict]:
    """Per lane over the last `since` seconds: waits on a held machine, refusals, cuts, answers beside a case, and the
    p95 of a delegation's whole latency (wait plus answer) against P95_TARGET_S for the lanes held to it."""
    now = time.time() if now is None else now
    rows = conn.execute("SELECT lane, waited_s, outcome, cut FROM serve_waits WHERE at >= ?", (now - since,)).fetchall()
    total = conn.execute("SELECT d.lane, d.seconds + COALESCE(w.waited_s, 0) AS s FROM delegations d "
                         "LEFT JOIN serve_waits w ON w.call_id = d.call_id AND w.call_id != '' "
                         "WHERE d.at >= ? AND d.seconds IS NOT NULL", (now - since,)).fetchall()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["lane"], []).append(r)
    latency: dict[str, list] = {}
    for r in total:
        latency.setdefault(r["lane"], []).append(float(r["s"]))
    out = []
    for lane in sorted(set(by) | set(latency)):
        items = by.get(lane, [])
        secs = [float(i["waited_s"] or 0.0) for i in items]
        p95 = _p95(latency.get(lane, []))
        held = lane in TARGET_LANES and p95 is not None
        out.append({"lane": lane, "waits": len(items),
                    "refused": sum(1 for i in items if i["outcome"] == REFUSED),
                    "cut": sum(1 for i in items if i["cut"]),
                    "beside": sum(1 for i in items if i["outcome"] == BESIDE),
                    "median_wait_s": round(statistics.median(secs), 3) if secs else None,
                    "max_wait_s": round(max(secs), 3) if secs else None,
                    "p95_s": p95, "target_s": P95_TARGET_S if lane in TARGET_LANES else None,
                    "over_target": held and p95 > P95_TARGET_S})
    return out


def yielded_s(progress: dict, now: float | None = None, since_case: bool = False) -> float:
    """Seconds a run's progress says it yielded to serving, a yield in progress too; only since its last case if asked."""
    got = progress.get("serving_yields") or {}
    total = float(got.get("since_case_s" if since_case else "seconds") or 0.0)
    if got.get("yielding_since") is not None:
        total += max(0.0, (time.time() if now is None else now) - float(got["yielding_since"]))
    return total


def worked_s(subject, now: float | None = None) -> float | None:
    """A watchdog subject's elapsed seconds less what its runs yielded to serving, which no time limit counts."""
    if subject.elapsed_s is None:
        return None
    return max(0.0, subject.elapsed_s - sum(yielded_s(r, now) for r in subject.runs()))


def during_yield(progress: dict, at: float, now: float | None = None) -> bool:
    """Whether `at` fell inside one of a run's yields to serving, one in progress included. #1558."""
    got = progress.get("serving_yields") or {}
    spans = [(float(a), float(b)) for a, b in got.get("spans") or []]
    if got.get("yielding_since") is not None:
        spans.append((float(got["yielding_since"]), time.time() if now is None else now))
    return any(a <= at <= b for a, b in spans)
