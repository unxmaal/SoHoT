"""`soh context --mistakes --repeats`: KB mistakes that repeat a recorded class, and known-bad command rates. #1696."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness import context_mistakes as cm
from harness import context_report as cr

#: Seconds before a repeat's recording call in which its stream's KB queries and results are read.
LOOKBACK_S = 12 * 3600
#: KB tables read: repeats are judged among negative and error rows; any of these can be the earlier entry.
KB_KINDS = ("negative", "error", "rule")
QUERY_TOOLS = ("search", "report_error")
_MCM = "mcp__mcm-engine__"
_CITED = re.compile(r"\b(RULE|NEGATIVE|ERROR) #(\d+)\b|#(\d+) \[(rule|negative|error)\]")
_LESSON = re.compile(r"^(RULE|NEGATIVE|ERROR) #(\d+)$")


@dataclass(frozen=True)
class Pattern:
    """One class of mistake: kb matches KB row text, command (if any) a Bash command, lesson splits the rates."""
    name: str
    kb: str
    command: str = ""
    lesson: str = ""


_GIT = r"\bgit\s+(?:-C\s+\S+\s+)?"
#: The single table of mistake classes; a pattern with a command is also counted in Bash calls.
PATTERNS = (
    Pattern("pgrep-f-waiter", r"\bpgrep\b",
            r"\b(?:until|while)\b[^;\n]*?\bpgrep(?:\s+-\w+)*?\s+-\w*f\w*\s+"
            r"""(?:"[^"\[]*"|'[^'\[]*'|[^\s"'\[;|&]+)(?=[\s;|&)>]|$)""", "RULE #906"),
    Pattern("git-add-all", r"git add (?:-A|--all|\.)(?![\w/])",
            _GIT + r"add\s+(?:-A|--all)\s*(?:$|[;&|)\n])", "NEGATIVE #31"),
    Pattern("pipe-tail-then-commit", r"\|\s*tail\b[^\n]*&&|exit status is tail",
            r"\|\s*tail\b[^\n;|]*&&\s*" + _GIT + r"commit\b", "NEGATIVE #41"),
    Pattern("launchctl-disable", r"launchctl disable", r"\blaunchctl\s+disable\b", "NEGATIVE #51"),
    Pattern("pytest-n-auto", r"-n auto\b|xdist workers", r"(?:^|\s)-n\s*auto\b", "NEGATIVE #53"),
    Pattern("checkout-ref-restore", r"git checkout (?!-)\S+ -- ", _GIT + r"checkout\s+(?!-)\S+\s+--\s+\S",
            "NEGATIVE #47"),
    Pattern("checkout-index-restore", r"git checkout -- ", _GIT + r"checkout\s+--\s+\S", "NEGATIVE #47"),
    Pattern("zsh-shell", r"\bzsh\b(?! -c)"),
    Pattern("worktree-guard", r"worktree.?guard|too complex to verify|names git in a form"),
    Pattern("red-proof-restore", r"not an inverse|inverse substitution|uncommitted edits|red-proof\w* by mutation only"),
    Pattern("inferred-not-observed", r"\binferred\b|without reading the log|not observed"),
    Pattern("merged-branch", r"already merged|stranded|was merged|onto main|after (?:announcing|reporting)"),
    Pattern("chained-exit-status", r"exit status|pipefail"),
    Pattern("parallel-suites", r"xdist|parallel make check|concurrent pytest"),
    Pattern("live-store-write", r"live store|read-only store"),
    Pattern("sync-rules", r"sync_rules"),
    Pattern("gate:mutation-modules", r"mutation\.py MODULES|test_gauntlet_mutation|mutated module"),
    Pattern("gate:knobs-unregistered", r"test_knobs|gating constant|knob backlog|unregistered"),
    Pattern("gate:swallowed-errors", r"swallowed"),
    Pattern("gate:detector-bound-test", r"detector without a bound test|test_gauntlet_detectors"),
    Pattern("gate:specs-capability", r"capabilities\.yaml|harness\.specs"),
    Pattern("gate:privacy-host", r"harness\.privacy|private-host|LAN address"),
    Pattern("gate:limit-trace", r"untraced|test_limit_trace"),
    Pattern("gate:sensitivity-inventory", r"sensitivity inventory|test_sensitivity"),
    Pattern("gate:one-question-two-answers", r"one-question-two-answers"),
    Pattern("gate:module-layout", r"test_module_layout"),
    Pattern("gate:loop-circuit", r"test_loop_circuit"),
)


def _week(at: float) -> str:
    y, w, _ = datetime.fromtimestamp(at, timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def _id(kind: str, n: int) -> str:
    return f"{kind.upper()} #{n}"


def streams(root: Path, since: float = 0.0):
    """(stream id, kind main|sub, records) per interactive session; subagents of workflows too, headless skipped."""
    from evals.analysis import demand
    from evals.importers import transcripts as tr
    for _project, main, _subs in tr.sessions(root):
        if main.stat().st_mtime < since:
            continue
        recs = [r for r in tr.records(main) if not r.get("isSidechain")]
        if demand._headless(recs):
            continue
        yield main.stem, "main", recs
        for sub in sorted((main.parent / main.stem / "subagents").rglob("*.jsonl")):
            yield f"{main.stem}/{sub.stem}", "sub", list(tr.records(sub))


def events(root: Path, since: float = 0.0) -> tuple[list[dict], list[dict]]:
    """Bash calls {stream, kind, at, cmd} and mcm-engine calls {stream, kind, tool, called, at, query, text}."""
    bash, mcm, seen = [], [], set()
    for stream, kind, recs in streams(root, since):
        open_calls = {}
        for rec in recs:
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            content = msg.get("content") if isinstance(msg.get("content"), list) else ()
            at = cr._epoch(rec.get("timestamp")) or 0.0
            for b in content:
                if not isinstance(b, dict):
                    continue
                uid = b.get("id")
                if rec.get("type") == "assistant" and b.get("type") == "tool_use" and uid not in seen:
                    seen.add(uid)
                    name, inp = str(b.get("name") or ""), b.get("input") if isinstance(b.get("input"), dict) else {}
                    if name == "Bash":
                        bash.append({"stream": stream, "kind": kind, "at": at, "cmd": str(inp.get("command") or "")})
                    elif name.startswith(_MCM):
                        call = {"stream": stream, "kind": kind, "tool": name[len(_MCM):], "called": at, "at": at,
                                "query": " ".join(str(v) for v in inp.values() if isinstance(v, str)), "text": ""}
                        open_calls[uid] = call
                        mcm.append(call)
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in open_calls:
                    call = open_calls.pop(b.get("tool_use_id"))
                    call["at"], call["text"] = at, cr.result_text(b.get("content"))
    return bash, mcm


def cited(text: str) -> set[str]:
    """KB ids a tool result names: '[RULE #906]' in search output or '#906 [rule]' in scroll output."""
    return {_id(m.group(1) or m.group(4), int(m.group(2) or m.group(3))) for m in _CITED.finditer(text)}


def _rate(n: int, total: int) -> float | None:
    return round(1000 * n / total, 2) if total else None


def _counts(hits: list[dict], pop: Counter, key, order=sorted) -> dict:
    got = Counter(key(b) for b in hits)
    return {k: {"calls": got[k], "bash": pop[k], "per_1k": _rate(got[k], pop[k])} for k in order(pop)}


def rates(bash: list[dict], patterns, lessons: dict, since: float, until: float) -> list[dict]:
    """Per command pattern: calls per 1k Bash calls main vs sub, before/after its lesson, by week; self-copies."""
    pop = [b for b in bash if since <= b["at"] < until]
    by_kind = Counter(b["kind"] for b in pop)
    by_week = Counter((_week(b["at"]), b["kind"]) for b in pop)
    out = []
    for p in patterns:
        if not p.command:
            continue
        rx = re.compile(p.command)
        hits = sorted((b for b in pop if rx.search(b["cmd"])), key=lambda b: b["at"])
        per_stream = Counter(b["stream"] for b in hits)
        row = {"pattern": p.name, "lesson": p.lesson or None, "lesson_at": lessons.get(p.lesson), "kinds": {}}
        for kind in ("main", "sub"):
            mine = [b for b in hits if b["kind"] == kind]
            streams_ = {b["stream"] for b in mine}
            row["kinds"][kind] = {"calls": len(mine), "bash": by_kind[kind], "per_1k": _rate(len(mine), by_kind[kind]),
                                  "streams": len(streams_),
                                  "streams_2plus": sum(1 for s in streams_ if per_stream[s] > 1),
                                  "self_copies": len(mine) - len(streams_)}
        split = row["lesson_at"]
        if split is not None:
            def side(b, split=split):
                return "before" if b["at"] < split else "after", b["kind"]
            got = _counts(hits, Counter(map(side, pop)), side, lambda c: sorted(c, key=lambda k: (k[0] != "before", k)))
            row["split"] = {f"{s} {k}": v for (s, k), v in got.items()}
        weeks = _counts(hits, by_week, lambda b: (_week(b["at"]), b["kind"]))
        row["weeks"] = [{"week": w, "kind": k, **v} for (w, k), v in weeks.items()]
        out.append(row)
    return out


def repeats(rows: list[dict], patterns, since: float, until: float) -> list[dict]:
    """One entry per (negative/error row in the window, class) whose class an earlier KB row already recorded."""
    out = []
    for p in patterns:
        rx = re.compile(p.kb, re.I)
        earlier: list[dict] = []
        for r in sorted((r for r in rows if rx.search(r.get("text") or "")), key=lambda r: (r["at"], r["id"])):
            prior = [e for e in earlier if e["at"] < r["at"]]
            if prior and r["kind"] in cm.MISTAKE_KINDS and since <= r["at"] < until:
                out.append({"kind": r["kind"], "id": r["id"], "at": r["at"], "class": p.name,
                            "earlier": _id(prior[-1]["kind"], prior[-1]["id"]), "earlier_at": prior[-1]["at"],
                            "first": _id(prior[0]["kind"], prior[0]["id"]), "earlier_n": len(prior),
                            "_ids": {_id(e["kind"], e["id"]) for e in prior}})
            earlier.append(r)
    return sorted(out, key=lambda x: (x["at"], x["kind"], x["id"], x["class"]))


def look_back(reps: list[dict], rows: list[dict], mcm: list[dict], patterns, since: float, until: float,
              lookback: float = LOOKBACK_S) -> None:
    """Join each repeat to its recording call; count the stream's KB queries before it and the lesson ids returned."""
    calls = [c for c in mcm if c["tool"] in cm.MISTAKE_TOOLS]
    mine = [r for r in rows if r["kind"] in cm.MISTAKE_KINDS and since <= r["at"] < until]
    joined, _ = cm.join(mine, calls, streams=("main", "sub"))
    call_of = {(j["class"], j["id"]): j for j in joined}
    by_stream = defaultdict(list)
    for c in mcm:
        by_stream[c["stream"]].append(c)
    kb = {p.name: re.compile(p.kb, re.I) for p in patterns}
    for rep in reps:
        c = call_of.get((rep["kind"], rep["id"]))
        rep["recorded"] = c["kind"] if c else None
        if not c:
            continue
        lo, hi = c["called"] - lookback, c["called"]
        before = [x for x in by_stream[c["stream"]] if lo <= x["called"] < hi]
        queries = [x for x in before if x["tool"] in QUERY_TOOLS]
        rep["queries"] = len(queries)
        rep["topical"] = sum(1 for x in queries if kb[rep["class"]].search(x["query"]))
        rep["returned"] = sorted(set().union(*(cited(x["text"]) for x in before if x["at"] < hi)) & rep["_ids"])
        rep["on_record"] = sorted(cited(c["text"]) & rep["_ids"])


def measure(root: Path, rows: list[dict], *, since: float | None = None, until: float | None = None,
            patterns=None, lookback: float = LOOKBACK_S) -> dict:
    """KB repeats with what the stream had searched and been shown, and command-pattern rates. Counts only."""
    since, until = since or 0.0, until if until is not None else float("inf")
    patterns = PATTERNS if patterns is None else patterns
    bash, mcm = events(root, max(0.0, since - lookback))
    lessons = {}
    for p in patterns:
        m = _LESSON.match(p.lesson)
        hit = [r["at"] for r in rows if m and r["kind"] == m.group(1).lower() and r["id"] == int(m.group(2))]
        if hit:
            lessons[p.lesson] = hit[0]
    reps = repeats(rows, patterns, since, until)
    look_back(reps, rows, mcm, patterns, since, until, lookback)
    window = [r for r in rows if r["kind"] in cm.MISTAKE_KINDS and since <= r["at"] < until]
    rep_rows = {(r["kind"], r["id"]) for r in reps}
    classes, ordered = [], sorted(rows, key=lambda r: (r["at"], r["id"]))
    for p in patterns:
        rx = re.compile(p.kb, re.I)
        n = Counter(r["kind"] for r in window if rx.search(r.get("text") or ""))
        k = Counter(r["kind"] for r in reps if r["class"] == p.name)
        first = next((r for r in ordered if rx.search(r.get("text") or "")), None)
        classes.append({"class": p.name, "command": bool(p.command), "negative": n["negative"], "error": n["error"],
                        "negative_repeats": k["negative"], "error_repeats": k["error"],
                        "first": _id(first["kind"], first["id"]) if first else None})
    rec = [r for r in reps if r.get("recorded")]
    for r in reps:
        r.pop("_ids")
    per_row: dict = {}
    for r in rec:
        acc = per_row.setdefault((r["kind"], r["id"]), {"queries": r["queries"], "topical": 0, "returned": False,
                                                         "on_record": False, "recorded": r["recorded"]})
        acc["topical"] += r["topical"]
        acc["returned"] |= bool(r["returned"])
        acc["on_record"] |= bool(r["on_record"])
    rows_ = list(per_row.values())
    summary = {"rows": dict(Counter(r["kind"] for r in window)),
               "repeat_rows": dict(Counter(k for k, _ in rep_rows)),
               "recorded": dict(Counter(f"{k} {v['recorded']}" for (k, _), v in per_row.items())),
               "no_query": sum(1 for v in rows_ if not v["queries"]),
               "topical_query": sum(1 for v in rows_ if v["topical"]),
               "returned_before": sum(1 for v in rows_ if v["returned"]),
               "returned_on_record": sum(1 for v in rows_ if v["on_record"])}
    return {"kb_rows": dict(Counter(r["kind"] for r in rows)), "summary": summary, "classes": classes,
            "repeats": reps, "bash": dict(Counter(b["kind"] for b in bash if since <= b["at"] < until)),
            "rates": rates(bash, patterns, lessons, since, until), "lookback_s": lookback}
