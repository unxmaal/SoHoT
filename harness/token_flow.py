"""Cloud counted tokens by stream kind, agent type and cache write cause, from Claude Code transcripts (#2031)."""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from harness import ledger

MAIN, SUB = "main", "subagent"
COLD, EXPIRED, REWRITE, GROWTH = "cold start", "rewrite after expiry", "rewrite, no idle gap", "growth"
COMPACTED = "rewrite after compaction"
CAUSES = (COLD, COMPACTED, EXPIRED, REWRITE, GROWTH)
#: Seconds a cache write lives, by the lifetime the request asked for (usage.cache_creation).
TTL_S = {"5m": 300.0, "1h": 3600.0}
NO_TOOL = "no tool in flight"
UNNAMED = "unnamed"
NO_PR = "opened no pull request"
PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
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


def cause(prev: dict | None, row: dict, compacted: bool = False) -> tuple[str, float | None]:
    """(cause, idle seconds) of one request's cache write, from the request before it and a compaction between."""
    if prev is None:
        return COLD, None
    idle = row["at"] - prev["at"]
    if compacted:
        return COMPACTED, idle
    if row["cache_read"] >= row["cache_write"]:
        return GROWTH, idle
    return (EXPIRED if idle > TTL_S[row["ttl"]] else REWRITE), idle


def kind_of(path, root=None) -> str:
    """subagent for a transcript under a subagents directory, read below `root` when given; else main."""
    p = Path(path)
    return SUB if "subagents" in (p.relative_to(root) if root is not None else p).parts else MAIN


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(str(b.get("text") or "") for b in c if isinstance(b, dict))
    return str(c or "")


class Marks:
    """Per transcript, the compaction boundaries and the pull requests a `gh pr create` in it opened, with times."""

    def __init__(self):
        self.compactions: dict = {}
        self.prs: dict = {}
        self._asked: dict = {}

    def line(self, path, line: str) -> None:
        if '"compact_boundary"' not in line and "gh pr create" not in line and not (
                self._asked.get(path) and '"tool_result"' in line):
            return
        try:
            rec = json.loads(line)
        except ValueError:
            return
        if not isinstance(rec, dict):
            return
        at = ledger._stamp(rec.get("timestamp"))
        if at is None:
            return
        if rec.get("type") == "system" and rec.get("subtype") == "compact_boundary":
            self.compactions.setdefault(path, []).append(at)
            return
        msg = rec.get("message")
        for block in msg.get("content") if isinstance(msg, dict) and isinstance(msg.get("content"), list) else ():
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash" and "gh pr create" in str(
                    (block.get("input") or {}).get("command") if isinstance(block.get("input"), dict) else ""):
                self._asked.setdefault(path, set()).add(block.get("id"))
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in self._asked.get(path, ()):
                m = PR_URL.search(_result_text(block))
                if m:
                    self.prs.setdefault(path, []).append((at, f"{m.group(1).lower()}#{m.group(2)}"))


def pr_of(opened: list, at: float, kind: str) -> str | None:
    """The pull request a request at `at` worked toward: the next one its stream opened, else a subagent's last."""
    for when, pr in opened:
        if when >= at:
            return pr
    return opened[-1][1] if opened and kind == SUB else None


#: One transcript's usage records and marks by (path, mtime_ns, size), kept on disk: a restart reads only the files that grew. #2191.
_SCANS: dict = {}
_SCAN_FORMAT = 1


def _scan(path) -> dict:
    """What `read` takes from one transcript: its usage records cut to the fields it folds, and its compaction and pull request marks."""
    marks, recs, agent = Marks(), [], ""
    for _p, rec, msg, at in ledger.usage_records([path], marks.line):
        agent = str(rec.get("attributionAgent") or agent)
        tool = None
        for block in msg.get("content") if isinstance(msg.get("content"), list) else ():
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool = tool_label(str(block.get("name") or "?"), block.get("input"))
        recs.append((ledger.usage_key(rec, msg), at, {"sessionId": rec.get("sessionId")},
                     {"model": msg.get("model"), "stop_reason": msg.get("stop_reason"),
                      "usage": {src: msg["usage"].get(src) for src, _name in ledger.USAGE_KEYS}},
                     lifetime(msg["usage"]), tool))
    return {"recs": recs, "agent": agent, "compactions": marks.compactions.get(path, []), "prs": marks.prs.get(path, [])}


def _scans(files) -> dict:
    """path -> `_scan` of each file, from the disk index when the file is unchanged, written back when any was read."""
    import os
    from harness import file_index
    if not _SCANS:
        _SCANS.update(file_index.read("transcripts", _SCAN_FORMAT))
    out, fresh = {}, False
    for path in files:
        try:
            st = os.stat(path)
        except OSError:
            continue
        key = (str(path), st.st_mtime_ns, st.st_size)
        if key not in _SCANS:
            _SCANS[key] = _scan(path)
            fresh = True
        out[path] = _SCANS[key]
    if fresh:
        here = {str(p) for p in out}
        file_index.write("transcripts", _SCAN_FORMAT, {k: v for k, v in _SCANS.items() if k[0] in here})
    return out


def read(files, since: float, until: float | None = None, root=None) -> list[dict]:
    """Each API request counted in the window, once, with its stream, agent type, cache write cause and pull request."""
    counted: dict = {}
    owner: dict = {}
    streams = []
    marks = Marks()
    files = list(files)
    for path, got in _scans(files).items():
        if not got["recs"]:
            continue
        marks.compactions[path], marks.prs[path] = got["compactions"], got["prs"]
        rows: dict = {}
        for key, at, rec, msg, ttl, tool in got["recs"]:
            owner.setdefault(key, len(streams))
            if ledger.in_window(at, since, until):
                ledger.merge_usage(counted, key, rec, msg, at)
            row = ledger.merge_usage(rows, key, rec, msg, at)
            row["ttl"] = ttl or row.get("ttl")
            if tool is not None:
                row["tool"] = tool
        streams.append({"stream": Path(path).stem, "kind": kind_of(path, root), "agent": got["agent"], "rows": rows,
                        "path": path})
    out = []
    for i, s in enumerate(streams):
        prev, ttl = None, "5m"
        bounds = marks.compactions.get(s["path"], [])
        opened = sorted(marks.prs.get(s["path"], []))
        for key, row in sorted(s["rows"].items(), key=lambda kv: kv[1]["at"]):
            ttl = row["ttl"] = row.get("ttl") or ttl
            why, idle = cause(prev, row, prev is not None and any(prev["at"] < b <= row["at"] for b in bounds))
            if owner[key] == i and key in counted:
                out.append({**counted[key], "stream": s["stream"], "kind": s["kind"],
                            "agent": s["agent"] if s["kind"] == SUB else "", "cause": why, "idle_s": idle, "ttl": ttl,
                            "after": (prev.get("tool") or NO_TOOL) if why == EXPIRED else None,
                            "pr": pr_of(opened, row["at"], s["kind"])})
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
    models = [{"kind": k, "agent": a or UNNAMED, "model": m, **g, "share": _share(g["counted"], n)}
              for (k, a, m), g in _group(reqs, lambda r: (r["kind"], r["agent"], r["model"])).items()]
    by_pr: dict = {}
    for r in reqs:
        if r.get("pr"):
            pm = by_pr.setdefault(r["pr"], {})
            pm[r["model"]] = pm.get(r["model"], 0) + _counted(r)
    prs = [{"pr": p, **g, "share": _share(g["counted"], n), "models": by_pr[p]}
           for p, g in _group([r for r in reqs if r.get("pr")], lambda r: r["pr"]).items()]
    no_pr = n - sum(p["counted"] for p in prs)
    return {"counted": n, "tokens": {k: total[k] for k in ledger._zero()}, "requests": total["requests"],
            "streams": total["streams"], "kinds": kinds, "agents": big(agents, "counted"),
            "models": big(models, "counted"),
            "causes": big(causes, "cache_write"), "expiry": expiry(rewrites, n), "terms": big(terms, "tokens"),
            "top": big(streams, "counted")[:max(0, top)], "prs": big(prs, "counted"),
            "no_pr": {"counted": no_pr, "share": _share(no_pr, n)}}


def merged_only(account_: dict, merged: set) -> dict:
    """The account's pull request rows cut to the merged ones; the rest fold into opened, not merged."""
    keep = [p for p in account_["prs"] if p["pr"] in merged]
    rest = sum(p["counted"] for p in account_["prs"] if p["pr"] not in merged)
    return {**account_, "prs": keep, "not_merged": {"counted": rest, "share": _share(rest, account_["counted"])}}


def merged_prs(prs: list[dict], gh) -> set:
    """Which of `prs` are merged, one `gh pr list` per repository; `gh(argv) -> stdout`."""
    out: set = set()
    for repo in sorted({p["pr"].split("#")[0] for p in prs}):
        got = gh(["pr", "list", "--repo", repo, "--state", "merged", "--limit", "1000", "--json", "number"])
        out |= {f"{repo}#{x['number']}" for x in json.loads(got or "[]")}
    return out


def expiry(rewrites: list[dict], counted: int) -> dict:
    """The rewrites after a cache expiry: their size, share of counted cloud, idle and what each waited on."""
    tools: dict = {}
    for r in rewrites:
        t = tools.setdefault(r["after"], {"cache_write": 0, "events": 0})
        t["cache_write"] += r["cache_write"]
        t["events"] += 1
    size = sum(r["cache_write"] for r in rewrites)
    by_ttl = {ttl: sum(r["cache_write"] for r in rewrites if r["ttl"] == ttl) for ttl in TTL_S}
    return {"cache_write": size, "events": len(rewrites), "share": _share(size, counted),
            "median_tokens": statistics.median(r["cache_write"] for r in rewrites) if rewrites else None,
            "median_idle_s": statistics.median(r["idle_s"] for r in rewrites) if rewrites else None,
            "by_ttl": {k: v for k, v in by_ttl.items() if v},
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
            "terms": got["terms"][:TERMS]}


def _pct(share: float | None) -> str:
    return "n/a" if share is None else f"{share:.0%}"


def terms_line(m: dict | None) -> str:
    """The morning line under the ratio: counted cloud and its largest terms."""
    if not m:
        return ""
    if not m.get("available"):
        return f"cloud     terms n/a: {m.get('why')}"
    parts = "; ".join(f"{t['term']} {ledger._mtok(t['tokens'])} ({_pct(t['share'])})" for t in m["terms"])
    return (f"cloud     {m['days']}d {ledger._mtok(m['counted'])} counted in transcripts; largest: {parts or 'none'}; "
            f"expiry rewrites {_pct(m['expiry']['share'])}")
