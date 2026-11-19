"""Cloud counted tokens by stream kind, agent type and cache write cause, from Claude Code transcripts (#2031)."""
from __future__ import annotations

import itertools
import re
import statistics
from pathlib import Path

from harness import ledger

MAIN, SUB = "main", "subagent"
COLD, EXPIRED, REWRITE, GROWTH = "cold start", "rewrite after expiry", "rewrite, no idle gap", "growth"
CAUSES = (COLD, EXPIRED, REWRITE, GROWTH)
#: Seconds a cache write lives, by the lifetime the request asked for (usage.cache_creation).
TTL_S = {"5m": 300.0, "1h": 3600.0}
NO_TOOL = "no tool in flight"
UNNAMED = "unnamed"
#: What a Bash call was waiting on, first match wins.
BASH_WAITS = (("CI wait (gh)", r"gh (run|pr) (watch|checks|view)|gh run list|until .*gh "),
              ("sleep or poll loop", r"\bsleep\b|until |while "),
              ("test suite run", r"pytest|make (check|test)|soh digest"),
              ("lint, gauntlet or mutation", r"make lint|gauntlet|mutation|mutmut"))
TOP = 10
TERMS = 3


def tool_label(name: str, inp) -> str:
    """A tool call as the account names it; a Bash call by what it waited on."""
    if name != "Bash":
        return name
    inp = inp if isinstance(inp, dict) else {}
    cmd = str(inp.get("command") or "")
    for label, pattern in BASH_WAITS:
        if re.search(pattern, cmd):
            return f"Bash: {label}"
    return "Bash: background" if inp.get("run_in_background") else "Bash: other"


def lifetime(usage: dict) -> str | None:
    """The cache lifetime a request wrote with, None when it wrote none or does not say."""
    cc = usage.get("cache_creation")
    cc = cc if isinstance(cc, dict) else {}
    five, hour = (int(cc.get(f"ephemeral_{k}_input_tokens") or 0) for k in ("5m", "1h"))
    return None if not five and not hour else "1h" if hour > five else "5m"


def cause(prev: dict | None, row: dict) -> tuple[str, float | None]:
    """(cause, idle seconds) of one request's cache write, from the request before it in its stream."""
    if prev is None:
        return COLD, None
    idle = row["at"] - prev["at"]
    if row["cache_read"] >= row["cache_write"]:
        return GROWTH, idle
    return (EXPIRED if idle > TTL_S[row["ttl"]] else REWRITE), idle


def kind_of(path, root=None) -> str:
    """subagent for a transcript under a subagents directory, read below `root` when given; else main."""
    p = Path(path)
    return SUB if "subagents" in (p.relative_to(root) if root is not None else p).parts else MAIN


def read(files, since: float, until: float | None = None, root=None) -> list[dict]:
    """Each API request counted in the window, once, with its stream, agent type and its cache write's cause."""
    counted: dict = {}
    owner: dict = {}
    streams = []
    for path, recs in itertools.groupby(ledger.usage_records(files), key=lambda r: r[0]):
        rows: dict = {}
        agent = ""
        for _path, rec, msg, at in recs:
            key = ledger.usage_key(rec, msg)
            owner.setdefault(key, len(streams))
            if ledger.in_window(at, since, until):
                ledger.merge_usage(counted, key, rec, msg, at)
            row = ledger.merge_usage(rows, key, rec, msg, at)
            row["ttl"] = lifetime(msg["usage"]) or row.get("ttl")
            agent = str(rec.get("attributionAgent") or agent)
            for block in msg.get("content") if isinstance(msg.get("content"), list) else ():
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    row["tool"] = tool_label(str(block.get("name") or "?"), block.get("input"))
        streams.append({"stream": Path(path).stem, "kind": kind_of(path, root), "agent": agent, "rows": rows})
    out = []
    for i, s in enumerate(streams):
        prev, ttl = None, "5m"
        for key, row in sorted(s["rows"].items(), key=lambda kv: kv[1]["at"]):
            ttl = row["ttl"] = row.get("ttl") or ttl
            why, idle = cause(prev, row)
            if owner[key] == i and key in counted:
                out.append({**counted[key], "stream": s["stream"], "kind": s["kind"],
                            "agent": s["agent"] if s["kind"] == SUB else "", "cause": why, "idle_s": idle, "ttl": ttl,
                            "after": (prev.get("tool") or NO_TOOL) if why == EXPIRED else None})
            prev = row
    return out


def _counted(t: dict) -> int:
    return sum(int(t.get(k) or 0) for k in ledger.CLOUD_COUNTED)


def _group(reqs, key) -> dict:
    out: dict = {}
    for r in reqs:
        g = out.setdefault(key(r), {**ledger._zero(), "requests": 0, "streams": set()})
        for k in ledger._zero():
            g[k] += r[k]
        g["requests"] += 1
        g["streams"].add((r["kind"], r["stream"]))
    for g in out.values():
        g["streams"], g["counted"] = len(g["streams"]), _counted(g)
    return out


def _share(n: int, of: int) -> float | None:
    return n / of if of else None


def account(reqs: list[dict], top: int = TOP) -> dict:
    """The counted cloud tokens of `reqs` as disjoint terms: by kind, agent type, cache write cause and stream."""
    total = _group(reqs, lambda r: "all").get("all") or {**ledger._zero(), "requests": 0, "streams": 0, "counted": 0}
    n = total["counted"]
    kinds = [{"kind": k, **g, "share": _share(g["counted"], n)}
             for k, g in sorted(_group(reqs, lambda r: r["kind"]).items())]
    agents = [{"agent": a or UNNAMED, **g, "share": _share(g["counted"], n)}
              for a, g in _group([r for r in reqs if r["kind"] == SUB], lambda r: r["agent"]).items()]
    writes: dict = {}
    for r in reqs:
        if r["cache_write"]:
            w = writes.setdefault((r["kind"], r["cause"]), {"cache_write": 0, "events": 0})
            w["cache_write"] += r["cache_write"]
            w["events"] += 1
    causes = [{"kind": k, "cause": c, **w, "share": _share(w["cache_write"], n)} for (k, c), w in writes.items()]
    terms = [{"term": f"{c['kind']} cache write, {c['cause']}", "tokens": c["cache_write"], "share": c["share"]}
             for c in causes]
    terms += [{"term": f"{k['kind']} {name}", "tokens": k[name], "share": _share(k[name], n)}
              for k in kinds for name in ("input", "output") if k[name]]
    per = _group(reqs, lambda r: (r["kind"], r["stream"], r["agent"]))
    rewrites = [r for r in reqs if r["cause"] == EXPIRED and r["cache_write"]]
    streams = [{"stream": s, "kind": k, "agent": a, **{x: g[x] for x in (*ledger._zero(), "requests", "counted")},
                "share": _share(g["counted"], n),
                "expiry_rewrites": sum(1 for r in rewrites if (r["kind"], r["stream"]) == (k, s))}
               for (k, s, a), g in per.items()]
    big = lambda rows, k: sorted(rows, key=lambda r: (-r[k], str(sorted(r.items()))))  # noqa: E731
    lives = [{"kind": k, "agent": a if k == SUB else "", "ttl": t, **g, "share": _share(g["counted"], n)}
             for (k, a, t), g in _group(reqs, lambda r: (r["kind"], r["agent"] or UNNAMED, r["ttl"])).items()]
    return {"counted": n, "tokens": {k: total[k] for k in ledger._zero()}, "requests": total["requests"],
            "streams": total["streams"], "kinds": kinds, "agents": big(agents, "counted"),
            "causes": big(causes, "cache_write"), "expiry": expiry(rewrites, n), "terms": big(terms, "tokens"),
            "top": big(streams, "counted")[:max(0, top)], "lifetimes": big(lives, "counted")}


def expiry(rewrites: list[dict], counted: int) -> dict:
    """The rewrites after a cache expiry: their size, share of counted cloud, idle and what each waited on."""
    tools: dict = {}
    for r in rewrites:
        t = tools.setdefault(r["after"], {"cache_write": 0, "events": 0})
        t["cache_write"] += r["cache_write"]
        t["events"] += 1
    size = sum(r["cache_write"] for r in rewrites)
    by_ttl = {ttl: sum(r["cache_write"] for r in rewrites if r["ttl"] == ttl) for ttl in TTL_S}
    kt: dict = {}
    for r in rewrites:
        kt.setdefault((r["kind"], r["ttl"]), []).append(r)
    by_kind = [{"kind": k, "ttl": t, "cache_write": sum(r["cache_write"] for r in rs), "events": len(rs),
                "share": _share(sum(r["cache_write"] for r in rs), counted),
                "median_idle_s": statistics.median(r["idle_s"] for r in rs)} for (k, t), rs in kt.items()]
    return {"cache_write": size, "events": len(rewrites), "share": _share(size, counted),
            "median_tokens": statistics.median(r["cache_write"] for r in rewrites) if rewrites else None,
            "median_idle_s": statistics.median(r["idle_s"] for r in rewrites) if rewrites else None,
            "by_ttl": {k: v for k, v in by_ttl.items() if v},
            "by_kind": sorted(by_kind, key=lambda g: (-g["cache_write"], g["kind"], g["ttl"])),
            "tools": sorted(({"tool": k, **v, "share": _share(v["cache_write"], size)} for k, v in tools.items()),
                            key=lambda t: (-t["cache_write"], t["tool"]))}


def gather(since: float, until: float | None = None, *, root=None, top: int = TOP) -> dict:
    """The account over every transcript under `root` touched since `since`; available False when there is none."""
    from harness import context_report as cr
    root = Path(root) if root is not None else cr.default_root()
    if not root.is_dir():
        return {"available": False, "why": "no Claude Code transcripts on this machine"}
    files = list(cr.transcripts(root, newer_than=since))
    return {"available": True, "files": len(files), "source": "transcripts", "lower_bound": True,
            **account(read(files, since, until, root), top)}


def morning(now: float, *, root=None) -> dict:
    """The account over the ratio's own week, ending yesterday, cut to its largest terms."""
    first = ledger.ratio_over({}, ledger.day_of(now - 86400), ledger.RATIO_DAYS)["first_day"]
    got = gather(ledger.day_start(first), ledger.day_start(ledger.day_of(now)), root=root, top=0)
    if not got["available"]:
        return got
    return {"available": True, "first_day": first, "last_day": ledger.day_of(now - 86400), "days": ledger.RATIO_DAYS,
            "counted": got["counted"], "expiry": {k: got["expiry"][k] for k in ("cache_write", "events", "share")},
            "terms": got["terms"][:TERMS], "short_lived": short_lived(got["lifetimes"])}


def short_lived(lifetimes: list[dict]) -> list[str]:
    """Subagent types that wrote a cache of the short lifetime, which any idle past it writes again whole (#2036)."""
    return sorted({g["agent"] for g in lifetimes if g["kind"] == SUB and g["ttl"] == "5m" and g["cache_write"]})


def _pct(share: float | None) -> str:
    return "n/a" if share is None else f"{share:.0%}"


def terms_line(m: dict | None) -> str:
    """The morning line under the ratio: counted cloud and its largest terms."""
    if not m:
        return ""
    if not m.get("available"):
        return f"cloud     terms n/a: {m.get('why')}"
    parts = "; ".join(f"{t['term']} {ledger._mtok(t['tokens'])} ({_pct(t['share'])})" for t in m["terms"])
    short = f"; subagents on a 5m cache: {', '.join(m['short_lived'])}" if m.get("short_lived") else ""
    return (f"cloud     {m['days']}d {ledger._mtok(m['counted'])} counted in transcripts; largest: {parts or 'none'}; "
            f"expiry rewrites {_pct(m['expiry']['share'])}{short}")
