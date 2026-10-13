"""Each delegated subtask and what became of its answer: used, edited or discarded. #829."""
from __future__ import annotations

import statistics
import sys
import time
import uuid

OUTCOMES = ("used", "edited", "discarded")
GATEWAY, LOCAL = "gateway", "local"


class UnknownCall(KeyError):
    """No delegation has this call id."""

    def __str__(self) -> str:
        return self.args[0]


def new_id() -> str:
    return "local-" + uuid.uuid4().hex


def record(conn, call_id: str, lane: str, spec: str = "", model: str = "",
           seconds=None, prompt_tokens=None, completion_tokens=None,
           id_source: str = LOCAL, at: float | None = None) -> str:
    conn.execute(
        "INSERT OR REPLACE INTO delegations (call_id, id_source, at, lane, spec, model, "
        "seconds, prompt_tokens, completion_tokens, outcome, why, outcome_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '', NULL)",
        (call_id, id_source, time.time() if at is None else at, lane, spec, model,
         seconds, prompt_tokens, completion_tokens))
    conn.commit()
    return call_id


def note(got: dict, call_id: str, gateway: bool = False) -> dict:
    """Record a delegate.complete/decide result as delegation `call_id`; a store failure never fails the call."""
    try:
        from harness import usage
        from harness import memory_store as ms
        path = usage.target()
        if path is None:
            return {**got, "call_id": call_id}
        conn = ms.connect(path)
        try:
            record(conn, call_id, got["lane"], spec=got.get("spec", ""),
                   model=got.get("model", ""), seconds=got.get("seconds"),
                   prompt_tokens=got.get("prompt_tokens"),
                   completion_tokens=got.get("completion_tokens"),
                   id_source=GATEWAY if gateway else LOCAL)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"delegations: not recorded ({exc})", file=sys.stderr)
    return {**got, "call_id": call_id}


def outcome(conn, call_id: str, what: str, why: str = "", at: float | None = None) -> dict:
    """Set a delegation's outcome; re-recording overwrites and keeps the old one in `why`."""
    what = (what or "").strip().lower()
    if what not in OUTCOMES:
        raise ValueError(f"outcome must be one of used, edited, discarded, not {what!r}")
    row = conn.execute("SELECT outcome, why FROM delegations WHERE call_id = ?",
                       (call_id,)).fetchone()
    if row is None:
        raise UnknownCall(f"no delegation has call id {call_id!r}; local_complete and "
                          f"local_decide return it as call_id")
    prev, prev_why = row["outcome"], row["why"]
    note_ = ""
    if prev is not None:
        why = f"{why} (was {prev}{': ' + prev_why if prev_why else ''})".strip()
        note_ = f"overwrote {prev}"
    conn.execute("UPDATE delegations SET outcome = ?, why = ?, outcome_at = ? WHERE call_id = ?",
                 (what, why, time.time() if at is None else at, call_id))
    conn.commit()
    return {"call_id": call_id, "outcome": what, "why": why, "previous": prev, "note": note_}


def report(conn, since: float, now: float | None = None) -> list[dict]:
    """Per lane over the last `since` seconds: count, recorded rate, outcome rates, median seconds."""
    now = time.time() if now is None else now
    rows = conn.execute("SELECT lane, outcome, seconds FROM delegations WHERE at >= ?",
                        (now - since,)).fetchall()
    by_lane: dict[str, list] = {}
    for r in rows:
        by_lane.setdefault(r["lane"], []).append(r)
    out = []
    for lane in sorted(by_lane):
        items = by_lane[lane]
        said = [i["outcome"] for i in items if i["outcome"] is not None]
        secs = [i["seconds"] for i in items if i["seconds"] is not None]
        out.append({
            "lane": lane, "count": len(items), "recorded": len(said),
            "recorded_rate": len(said) / len(items),
            **{f"{o}_rate": (said.count(o) / len(said) if said else None) for o in OUTCOMES},
            "median_seconds": round(statistics.median(secs), 3) if secs else None,
        })
    return out
