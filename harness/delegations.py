"""Each delegated subtask and what became of its answer: reported, inferred from the caller's transcript, or expired. #829, #1158."""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import sys
import time
import uuid
from pathlib import Path

#: What a caller reports with `delegated`.
OUTCOMES = ("used", "edited", "discarded")
#: What close() infers, or writes once a call is past EXPIRY_H with no evidence.
ACCEPTED, REJECTED, UNKNOWN, PENDING = "accepted", "rejected", "unknown", "pending"
INFERRED = (ACCEPTED, REJECTED, UNKNOWN)
KINDS = (ACCEPTED, REJECTED, UNKNOWN, PENDING)
_KIND = {"used": ACCEPTED, "edited": ACCEPTED, ACCEPTED: ACCEPTED,
         "discarded": REJECTED, REJECTED: REJECTED, UNKNOWN: UNKNOWN}
GATEWAY, LOCAL = "gateway", "local"

#: Hours after a call with no evidence before its outcome becomes unknown.
EXPIRY_H = 24.0
#: An answer or prompt line shorter than this, whitespace collapsed, is not looked for.
SPAN_CHARS = 30
#: Share of the answer's own lines a later tool input must hold to count the answer accepted.
SPAN_SHARE = 0.25

#: The MCP tools whose result carries a call_id.
DELEGATING = ("local_complete", "local_decide")


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


def kind(outcome) -> str:
    """accepted, rejected, unknown, or pending for a NULL outcome."""
    return _KIND.get(outcome or "", PENDING)


def instruction(call_id: str) -> str:
    """The sentence every local_complete / local_decide result carries. #1158."""
    return (f"Once you have used, edited or discarded this answer, call delegated with call_id "
            f"{call_id!r} and that outcome. Unreported, it is inferred from this session's later tool "
            f"inputs, or recorded unknown after {EXPIRY_H:g} h.")


def report(conn, since: float, now: float | None = None) -> list[dict]:
    """Per lane over the last `since` seconds: count, reported rate and rates, closed kinds, median seconds."""
    now = time.time() if now is None else now
    rows = conn.execute("SELECT lane, outcome, seconds FROM delegations WHERE at >= ?",
                        (now - since,)).fetchall()
    by_lane: dict[str, list] = {}
    for r in rows:
        by_lane.setdefault(r["lane"], []).append(r)
    out = []
    for lane in sorted(by_lane):
        items = by_lane[lane]
        said = [i["outcome"] for i in items if i["outcome"] in OUTCOMES]
        secs = [i["seconds"] for i in items if i["seconds"] is not None]
        kinds = [kind(i["outcome"]) for i in items]
        out.append({
            "lane": lane, "count": len(items), "recorded": len(said),
            "recorded_rate": len(said) / len(items),
            **{f"{o}_rate": (said.count(o) / len(said) if said else None) for o in OUTCOMES},
            **{k: kinds.count(k) for k in KINDS},
            "median_seconds": round(statistics.median(secs), 3) if secs else None,
        })
    return out


# --- closing outcomes from the caller's transcript (#1158) -----------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.split())


def spans(text: str, floor: int | None = None) -> set[str]:
    """The text's lines and sentences, whitespace collapsed, of at least `floor` characters."""
    floor = SPAN_CHARS if floor is None else floor
    out = set()
    for line in (text or "").splitlines():
        for part in re.split(r"(?<=[.!?])\s+", line):
            n = _norm(part)
            if len(n) >= floor:
                out.add(n)
    return out


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def _short(name: str) -> str:
    return name.rsplit("__", 1)[-1]


def _answer(name: str, body: dict) -> str:
    if _short(name) == "local_decide":
        return json.dumps(body.get("answers") or {}, sort_keys=True)
    return str(body.get("text") or "")


def _asked(name: str, given: dict) -> str:
    keys = ("question", "context") if _short(name) == "local_decide" else ("prompt", "question", "system")
    return "\n".join(str(given.get(k) or "") for k in keys)


def calls(path: Path, wanted) -> list[dict]:
    """Each delegation in `wanted` this transcript returned: its answer, its prompt, and every later tool input."""
    from harness.context_report import result_text
    wanted = set(wanted)
    with open(path, encoding="utf-8", errors="ignore") as fh:
        lines = [ln for ln in fh if '"tool_use"' in ln or '"tool_result"' in ln]
    if not any(c in ln for ln in lines for c in wanted):
        return []
    uses: dict = {}
    order: list[tuple] = []
    found: list[dict] = []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        content = (d.get("message") or {}).get("content") if isinstance(d, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                name = str(c.get("name") or "")
                given = c.get("input") if isinstance(c.get("input"), dict) else {}
                uses[c.get("id")] = (name, given)
                order.append((name, "\n".join(_strings(given))))
            elif c.get("type") == "tool_result" and not c.get("is_error"):
                name, given = uses.get(c.get("tool_use_id"), ("", {}))
                if _short(name) not in DELEGATING:
                    continue
                try:
                    body = json.loads(result_text(c.get("content")))
                except ValueError:
                    continue
                call_id = body.get("call_id") if isinstance(body, dict) else None
                if call_id in wanted:
                    found.append({"call_id": call_id, "tool": _short(name), "answer": _answer(name, body),
                                  "prompt": _asked(name, given), "after": len(order)})
    for f in found:
        f["later"] = order[f.pop("after"):]
    return found


def judge(answer: str, prompt: str, later, floor: int | None = None,
          share: float | None = None, near: list | None = None) -> tuple[str, str] | None:
    """(accepted|rejected, why) from the first later tool input that shows it, else None; `near` gets a miss under the share."""
    share = SPAN_SHARE if share is None else share
    asked = spans(prompt, floor)
    mine = spans(answer, floor) - asked
    need, again = max(1, math.ceil(share * len(mine))), max(1, math.ceil(share * len(asked)))
    from harness.context_report import SPAWN_TOOLS
    under = False
    for name, text in later:
        if _short(name) in DELEGATING:
            continue
        flat = _norm(text)
        hit = sum(1 for s in mine if s in flat)
        if mine and hit >= need:
            return ACCEPTED, f"{hit} of {len(mine)} answer lines in a later {_short(name)} input"
        if name in SPAWN_TOOLS and asked and sum(1 for s in asked if s in flat) >= again:
            return REJECTED, f"the task was asked again of a cloud {name}"
        under = under or hit > 0
    if under and near is not None:
        near.append(answer)
    return None


def _session(path: Path) -> str:
    return hashlib.sha256(path.stem.encode()).hexdigest()[:12]


def close(conn, root: Path | None = None, now: float | None = None, expiry_h: float | None = None) -> dict:
    """Infer each pending delegation's outcome from its caller's transcript; past expiry_h with none, unknown."""
    from harness import context_report as cr
    now = time.time() if now is None else now
    expiry_s = (EXPIRY_H if expiry_h is None else expiry_h) * 3600
    pending = {r["call_id"]: r["at"] for r in conn.execute(
        "SELECT call_id, at FROM delegations WHERE outcome IS NULL")}
    got = {k: 0 for k in INFERRED} | {PENDING: 0, "transcripts": 0}
    if not pending:
        return got
    root = cr.default_root() if root is None else Path(root)
    seen: dict = {}
    if root.is_dir():
        for path in cr.transcripts(root, newer_than=min(pending.values()) - 60):
            got["transcripts"] += 1
            for f in calls(path, set(pending) - set(seen)):
                seen[f["call_id"]] = (path, f)
    near: list = []
    expired = short = 0
    for call_id, at in sorted(pending.items()):
        what = why = None
        path, f = seen.get(call_id, (None, None))
        if f is not None:
            verdict = judge(f["answer"], f["prompt"], f["later"], near=near)
            if verdict:
                what, why = verdict[0], f"inferred from session {_session(path)}: {verdict[1]}"
        if what is None and now - at >= expiry_s:
            reason = ("no transcript under the projects root returned it" if f is None
                      else "no later tool input held the answer" if spans(f["answer"])
                      else "the answer has no line long enough to look for")
            what, why = UNKNOWN, f"expired after {expiry_s / 3600:g} h: {reason}"
            expired += 1
            short += f is not None and bool(f["answer"].strip()) and not spans(f["answer"])
        if what is None:
            got[PENDING] += 1
            continue
        cur = conn.execute("UPDATE delegations SET outcome = ?, why = ?, outcome_at = ? "
                           "WHERE call_id = ? AND outcome IS NULL", (what, why, now, call_id))
        got[what] += cur.rowcount
    from harness import cuts
    if expired:
        cuts.cut("delegation_expiry", "delegations closed unknown at expiry", value=expiry_s / 3600,
                 dropped=expired, conn=conn)
    if short:
        cuts.cut("delegation_span_chars", "delegation answers with no line long enough to look for", dropped=short,
                 conn=conn)
    if near:
        cuts.cut("delegation_span_share", "delegation answers seen in later input below the share",
                 dropped=len(near), conn=conn)
    conn.commit()
    return got
