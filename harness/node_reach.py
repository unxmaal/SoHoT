"""When the gateway took each serving node out of routing and put it back, from its own reach log. #1808."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

DOWN, UP = "down", "up"


def path() -> Path:
    from harness import paths
    return paths.home() / "nodes" / "reach.jsonl"


def record(node: str, state: str, why: str = "", at: float | None = None, where: Path | None = None) -> None:
    """Append one transition; a write that fails costs the log a line, never the request."""
    p = where or path()
    line = json.dumps({"at": time.time() if at is None else at, "node": node, "state": state, "why": why})
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        print(f"node_reach: {p}: {exc}", file=sys.stderr)


def read(where: Path | None = None) -> list[dict]:
    p = where or path()
    if not p.is_file():
        return []
    rows = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        try:
            got = json.loads(raw)
        except ValueError:
            continue
        if isinstance(got, dict) and got.get("state") in (DOWN, UP) and got.get("node"):
            rows.append(got)
    return sorted(rows, key=lambda r: float(r.get("at") or 0))


def outages(rows: list[dict], since: float, now: float) -> dict:
    """{node: [{start, end (None while still down), why}]} for each time out of routing that overlaps [since, now]."""
    by: dict = {}
    open_: dict = {}
    for r in rows:
        node, at = str(r["node"]), float(r["at"])
        if at > now:
            break
        if r["state"] == DOWN and node not in open_:
            open_[node] = {"start": at, "end": None, "why": str(r.get("why") or "")}
        elif r["state"] == UP and node in open_:
            got = open_.pop(node)
            got["end"] = at
            if at >= since:
                by.setdefault(node, []).append(got)
    for node, got in open_.items():
        by.setdefault(node, []).append(got)
    return {n: sorted(v, key=lambda o: o["start"]) for n, v in sorted(by.items())}


def summary(since: float, now: float, where: Path | None = None) -> list[dict]:
    """Per node: outages in the window, seconds out of routing inside it, and whether it is out now."""
    out = []
    for node, spans in outages(read(where), since, now).items():
        held = sum(min(o["end"] if o["end"] is not None else now, now) - max(o["start"], since) for o in spans)
        out.append({"node": node, "outages": spans, "down_s": max(held, 0.0), "down_now": spans[-1]["end"] is None})
    return out


def _span(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def line(n: dict) -> str:
    last = n["outages"][-1]
    when = time.strftime("%m-%d %H:%M:%S", time.localtime(last["start"]))
    tail = ("still out, not seen up since" if last["end"] is None
            else f"back after {_span(last['end'] - last['start'])}")
    why = f" ({last['why']})" if last["why"] else ""
    return (f"{n['node']} out of routing {len(n['outages'])} time(s), {_span(n['down_s'])} in all; "
            f"last {when}{why}, {tail}")
