"""Tool-result sizes entering Claude's context, read from Claude Code transcripts. #828."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

#: Results above this many estimated tokens count toward the "share over 2k" column.
BIG = 2000


def default_root() -> Path:
    return Path(os.environ.get("SOH_CLAUDE_PROJECTS") or Path.home() / ".claude" / "projects")


def parse_when(text, now: float) -> float:
    """'7d'/'12h' back from now, or an ISO date or datetime (UTC when no zone), as epoch seconds."""
    from harness.usage import parse_since

    raw = str(text).strip()
    if raw[-1:].lower() in "dhms" and raw[:-1].replace(".", "", 1).isdigit():
        return now - parse_since(raw)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"cannot read {text!r} as a time; use 7d, 12h, 2026-10-06 "
                         "or 2026-10-06T23:31Z") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _epoch(stamp) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def display_name(name: str) -> str:
    """mcp__mcm-engine__search reads as 'mcm-engine search'."""
    if name.startswith("mcp__"):
        parts = name[5:].split("__", 1)
        return " ".join(parts)
    return name


def result_text(body) -> str:
    """A tool_result's text: a string, or a list of blocks of which only text blocks count."""
    if isinstance(body, str):
        return body
    if isinstance(body, list):
        return "".join(b.get("text") or "" for b in body
                       if isinstance(b, dict) and b.get("type", "text") == "text")
    return ""


def transcripts(root: Path, *, main_only: bool = False, newer_than: float | None = None):
    """Every transcript under root; subagent ones too unless main_only. Files untouched since newer_than are skipped."""
    for p in sorted(Path(root).rglob("*.jsonl")):
        if main_only and "subagents" in p.relative_to(root).parts:
            continue
        if newer_than is not None and p.stat().st_mtime < newer_than:
            continue
        yield p


def scan(files, *, since: float | None = None, until: float | None = None) -> list[dict]:
    """One row per tool result: tool, tokens (chars // 4), at, day. Each tool_use_id counts once."""
    names: dict[str, str] = {}
    pending: list[tuple] = []
    seen: set = set()
    for path in files:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"tool_use"' not in line and '"tool_result"' not in line:
                    continue
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
                        names[c.get("id")] = c.get("name") or "?"
                    elif c.get("type") == "tool_result":
                        uid = c.get("tool_use_id")
                        key = uid if uid is not None else (str(path), d.get("uuid"), len(pending))
                        if key in seen:
                            continue
                        at = _epoch(d.get("timestamp"))
                        if at is not None and ((since is not None and at < since)
                                               or (until is not None and at >= until)):
                            continue
                        seen.add(key)
                        pending.append((uid, len(result_text(c.get("content"))) // 4, at))
    rows = []
    for uid, tokens, at in pending:
        day = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d") if at else "?"
        rows.append({"tool": display_name(names.get(uid, "?")), "tokens": tokens,
                     "at": at, "day": day})
    return rows


def stats(tokens: list[int]) -> dict:
    v = sorted(tokens)
    n, total = len(v), sum(v)
    big = sum(x for x in v if x > BIG)
    return {"calls": n, "tokens": total,
            "p50": v[n // 2] if v else 0,
            "p95": v[int(n * 0.95)] if v else 0,
            "max": v[-1] if v else 0,
            "share_over_2k": round(big / total, 4) if total else 0.0}


def summarize(rows: list[dict], by: str = "tool") -> list[dict]:
    """Stats per tool or per day, biggest token total first (days in order)."""
    groups: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        groups[r[by]].append(r["tokens"])
    out = [{by: k, **stats(v)} for k, v in groups.items()]
    if by == "day":
        return sorted(out, key=lambda r: r["day"])
    return sorted(out, key=lambda r: (-r["tokens"], r[by]))


def rtk_gain(runner=subprocess.run) -> dict | None:
    """rtk's own savings report, or None when rtk is not on PATH or says nothing readable."""
    if not shutil.which("rtk"):
        return None
    try:
        proc = runner(["rtk", "gain", "--all", "--format", "json"],
                      capture_output=True, text=True, timeout=60)
        return json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
