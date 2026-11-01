"""`soh context --mistakes`: do KB mistakes cluster after a compaction or at a context size? Counts only. #1381."""
from __future__ import annotations

import json
import re
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from harness import context_report as cr

#: Messages after a compaction that each reported window spans.
WINDOWS = (10, 25, 50, 100)
#: Lower edges, in input tokens, of the context-size bands.
BANDS = (0, 100_000, 200_000, 400_000, 600_000, 800_000)
#: Seconds between a KB row's insert time and its tool call's result within which they are one event.
MATCH_S = 120
#: The tool each KB table is written by; the control class is KB writes that are not mistakes.
MISTAKE_TOOLS = {"add_negative": "negative", "report_error": "error"}
CONTROL_TOOLS = ("add_knowledge", "add_rule")
_ROW = re.compile(r"^#(\d+) \[(negative|error)\]")
_AT = re.compile(r"updated=(\d{4}-\d\d-\d\d[ T][\d:.]+(?:[+-]\d\d:?\d\d|Z)?)")
PAGE = 100


def upper_tail(ps: list[float], k: int) -> float:
    """P(sum of independent Bernoulli(p) >= k), exact by convolution; equal ps make it the binomial tail."""
    if k <= 0:
        return 1.0
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for i, q in enumerate(dist):
            nxt[i] += q * (1 - p)
            nxt[i + 1] += q * p
        dist = nxt
    return min(1.0, sum(dist[k:]))


def _epoch(text) -> float | None:
    try:
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def parse_rows(text: str) -> list[dict]:
    """KB rows {kind, id, at} from mcm-engine scroll_entries pages, raw or as {"result": ...} JSON lines."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                got = json.loads(line)
            except ValueError:
                got = None
            if isinstance(got, dict) and isinstance(got.get("result"), str):
                lines.extend(got["result"].splitlines())
                continue
        lines.append(line)
    rows, cur = {}, None
    for line in lines:
        m = _ROW.match(line)
        if m:
            cur = (m.group(2), int(m.group(1)))
            continue
        a = _AT.search(line) if cur else None
        if a:
            at = _epoch(a.group(1))
            if at is not None:
                rows[cur] = {"kind": cur[0], "id": cur[1], "at": at}
            cur = None
    return sorted(rows.values(), key=lambda r: (r["at"], r["kind"], r["id"]))


def _post(url: str, body: dict, session: str | None) -> tuple[str | None, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.headers.get("Mcp-Session-Id"), r.read().decode("utf-8", "replace")


def _result_text(raw: str) -> str:
    for line in raw.splitlines():
        line = line[5:].strip() if line.startswith("data:") else line.strip()
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and isinstance(msg.get("result"), dict):
            return "\n".join(c.get("text") or "" for c in msg["result"].get("content") or [] if isinstance(c, dict))
    return ""


def fetch_rows(url: str, post=_post) -> list[dict]:
    """Page every negative and error row from an mcm-engine MCP URL with the read-only scroll_entries tool."""
    session, _ = post(url, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "soh-context", "version": "1"}}},
        None)
    post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    text, n = [], 1
    for kind in ("negative", "error"):
        after = 0
        while True:
            n += 1
            _, raw = post(url, {"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {
                "name": "scroll_entries", "arguments": {"entity_type": kind, "after_id": after, "limit": PAGE}}},
                session)
            page = _result_text(raw)
            ids = [int(m.group(1)) for m in map(_ROW.match, page.splitlines()) if m]
            if not ids:
                break
            text.append(page)
            after = max(ids)
    return parse_rows("\n".join(text))


def load_rows(source: str) -> list[dict]:
    """KB rows from an mcm-engine MCP URL or a saved file of scroll_entries pages."""
    if source.startswith(("http://", "https://")):
        return fetch_rows(source)
    return parse_rows(Path(source).read_text(encoding="utf-8", errors="replace"))


def _walk(session: str, kind: str, recs: list[dict], usage: dict, seen: set, msgs: list, calls: list) -> int:
    """Messages (session, at, position after the last compaction or None, context) and KB-write calls of a stream."""
    pos, compactions, mids, open_calls = None, 0, {}, {}
    for rec in recs:
        rtype = rec.get("type")
        if rtype == "system" and rec.get("subtype") == "compact_boundary":
            key = ("compact", rec.get("uuid") or rec.get("timestamp"))
            pos, compactions = 0, compactions + (key not in seen)
            seen.add(key)
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else ()
        if rtype == "assistant":
            mid = msg.get("id") or rec.get("uuid")
            if mid not in mids:
                pos = pos + 1 if pos is not None else None
                mids[mid] = {"session": session, "kind": kind, "pos": pos,
                             "ctx": usage[mid].tokens_in if mid in usage else 0,
                             "at": usage[mid].at if mid in usage else (cr._epoch(rec.get("timestamp")) or 0.0)}
                if mid in usage:
                    msgs.append(mids[mid])
            for b in content:
                if not (isinstance(b, dict) and b.get("type") == "tool_use") or b.get("id") in seen:
                    continue
                tool = str(b.get("name") or "").rsplit("__", 1)[-1]
                if tool in MISTAKE_TOOLS or tool in CONTROL_TOOLS:
                    seen.add(b.get("id"))
                    open_calls[b.get("id")] = call = {**mids[mid], "tool": tool,
                                                      "at": cr._epoch(rec.get("timestamp")) or 0.0}
                    calls.append(call)
        elif rtype == "user":
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in open_calls:
                    open_calls.pop(b.get("tool_use_id"))["at"] = cr._epoch(rec.get("timestamp")) or 0.0
    return compactions


def join(rows: list[dict], calls: list[dict], slack: float = MATCH_S) -> tuple[list[dict], Counter]:
    """Each KB row joined to the unused call of its kind nearest in time within slack; the rest counted as left out."""
    by_kind = defaultdict(list)
    for c in calls:
        if c["tool"] in MISTAKE_TOOLS:
            by_kind[MISTAKE_TOOLS[c["tool"]]].append(c)
    used, joined, left = set(), [], Counter()
    for r in rows:
        near = [c for c in by_kind[r["kind"]] if id(c) not in used and abs(c["at"] - r["at"]) <= slack]
        if not near:
            left[f"{r['kind']} no call"] += 1
            continue
        c = min(near, key=lambda c: abs(c["at"] - r["at"]))
        used.add(id(c))
        if c["kind"] != "main":
            left[f"{r['kind']} {c['kind']}"] += 1
            continue
        joined.append({**c, "class": r["kind"], "id": r["id"], "row_at": r["at"]})
    return joined, left


def _band(ctx: int, bands=BANDS) -> str:
    lo = max([b for b in bands if b <= ctx] or [bands[0]])
    hi = [b for b in bands if b > lo]
    return f"{lo // 1000}k-{hi[0] // 1000}k" if hi else f"{lo // 1000}k+"


def _test(msgs: list[dict], events: list[dict], inside) -> dict:
    """Share of messages and of events where inside() holds, pooled exact binomial and per-session tails."""
    per = defaultdict(lambda: [0, 0])
    for m in msgs:
        per[m["session"]][0] += 1
        per[m["session"]][1] += bool(inside(m))
    hit = sum(v[1] for v in per.values())
    share = hit / len(msgs) if msgs else 0.0
    k = sum(1 for e in events if inside(e))
    n = len(events)
    own = [per[e["session"]][1] / per[e["session"]][0] if per[e["session"]][0] else 0.0 for e in events]
    return {"messages": hit, "message_share": round(share, 4), "events": k, "events_total": n,
            "event_share": round(k / n, 4) if n else 0.0,
            "lift": round((k / n) / share, 2) if n and share else None,
            "p_binomial": upper_tail([share] * n, k), "p_session": upper_tail(own, k)}


def measure(root: Path, rows: list[dict], *, since: float | None = None, until: float | None = None,
            windows=WINDOWS, bands=BANDS, slack: float = MATCH_S) -> dict:
    """Windows after compaction and context bands: messages vs KB mistakes vs the control class. Counts only."""
    since, until = since or 0.0, until if until is not None else float("inf")
    msgs, calls, seen = [], [], set()
    streams, compactions = Counter(), 0
    for session, kind, recs, usage in cr.labelled_streams(root, 0.0, headless=True):
        streams[kind] += 1
        got = _walk(session, kind, recs, usage, seen, msgs if kind == "main" else [], calls)
        compactions += got if kind == "main" else 0
    msgs = [m for m in msgs if since <= m["at"] < until]
    rows = [r for r in rows if since <= r["at"] < until]
    joined, left = join(rows, calls, slack)
    control = [c for c in calls if c["tool"] in CONTROL_TOOLS and c["kind"] == "main" and since <= c["at"] < until]
    classes = {"negative": [j for j in joined if j["class"] == "negative"],
               "error": [j for j in joined if j["class"] == "error"], "mistakes": joined, "control": control}
    out = {"messages": len(msgs), "sessions": len({m["session"] for m in msgs}), "streams": dict(streams),
           "compactions": compactions, "kb_rows": len(rows), "joined": len(joined), "left_out": dict(left),
           "control": len(control), "windows": [], "bands": []}
    for w in windows:
        for name, ev in classes.items():
            out["windows"].append({"window": w, "class": name,
                                   **_test(msgs, ev, lambda m, w=w: m["pos"] is not None and m["pos"] <= w)})
    for band in dict.fromkeys(_band(b, bands) for b in bands):
        for name, ev in classes.items():
            out["bands"].append({"band": band, "class": name,
                                 **_test(msgs, ev, lambda m, band=band: _band(m["ctx"], bands) == band)})
    out["positions"] = sorted((j["pos"], j["ctx"], j["class"]) for j in joined if j["pos"] is not None)
    out["tests"] = len(out["windows"]) + len(out["bands"])
    return out
