"""`soh context --carried --by class`: what carried tool output was and whether Claude used it. #1333."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

from evals import session_cut
from harness import context_report as cr

#: A result of at least this many estimated tokens is a big one (the "over 1k" columns).
BIG = 1000
KB_PREFIX = "mcp__mcm-engine__"
_HIT = re.compile(r"\[(KNOWLEDGE/[A-Z_]+|NEGATIVE|ERROR|RULE) #(\d+)\]")
_REF = re.compile(r"#(\d+)\b")
_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
_SEGMENTS = re.compile(r"\s*(?:&&|\|\||;|\n)\s*")
_WRAPPERS = {"command", "time", "env", "rtk", "sudo", "nohup", "exec"}
_VIEWERS = {"cat", "sed", "head", "tail", "awk", "nl", "less", "more", "bat"}
_SEARCHERS = {"rg", "grep", "egrep", "find", "fd", "ls", "tree"}
_LOGS = (".log", ".txt", ".jsonl", ".output")
_KINDS = {".py": "python", ".md": "markdown", ".txt": ".txt", ".diff": ".diff", ".patch": ".diff",
          ".log": ".log", ".jsonl": ".jsonl", ".json": ".json", ".yaml": ".yaml", ".yml": ".yaml"}
#: Bash classes, the first that matches any segment of a command winning.
BASH_ORDER = ("Bash pytest / make check", "Bash gh issue/pr view, gh api", "Bash diff/log/show",
              "Bash reading log/txt/jsonl files", "Bash cat/sed/head/tail/awk", "Bash rg/grep/find/ls",
              "Bash git other", "Bash python", "Bash other")


def _words(segment: str) -> list[str]:
    words = [w.strip("\"'()") for w in segment.split()]
    while words and (words[0] in _WRAPPERS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0])):
        words.pop(0)
    if words:
        words[0] = os.path.basename(words[0])
    return words


def _git_sub(words: list[str]) -> str:
    rest = iter(words[1:])
    for w in rest:
        if w in ("-C", "-c", "--git-dir", "--work-tree"):
            next(rest, None)
        elif not w.startswith("-"):
            return w
    return ""


def _segment_class(words: list[str]) -> str:
    if not words or words[0] == "cd":
        return "Bash other"
    first = words[0]
    if any(os.path.basename(w) == "pytest" for w in words) or \
            (first == "make" and any(w in ("check", "test", "lint") for w in words[1:])):
        return BASH_ORDER[0]
    if first == "gh" and len(words) > 1 and (words[1] == "api" or
                                            (words[1] in ("issue", "pr") and words[2:3] == ["view"])):
        return BASH_ORDER[1]
    if first == "diff" or (first == "git" and _git_sub(words) in ("diff", "log", "show")) or \
            (first == "gh" and words[1:3] == ["pr", "diff"]):
        return BASH_ORDER[2]
    if first in _VIEWERS | _SEARCHERS | {"wc", "jq"} and any(w.endswith(_LOGS) for w in words[1:]):
        return BASH_ORDER[3]
    if first in _VIEWERS:
        return BASH_ORDER[4]
    if first in _SEARCHERS:
        return BASH_ORDER[5]
    if first == "git":
        return BASH_ORDER[6]
    if first.startswith("python") or (first == "uv" and any(w.startswith("python") for w in words)):
        return BASH_ORDER[7]
    return BASH_ORDER[8]


def bash_class(command: str) -> str:
    """The highest class of BASH_ORDER any segment's pipeline head falls in; a pipe tail only trims output."""
    found = {_segment_class(_words(s.split("|")[0])) for s in _SEGMENTS.split(command or "") if s.strip()}
    return next((c for c in BASH_ORDER if c in found), BASH_ORDER[-1])


def is_body(command: str) -> bool:
    """A command that carries an issue, PR, comment or commit body Claude wrote."""
    for s in _SPLIT.split(command or ""):
        w = _words(s)
        if w[:1] == ["gh"] and w[1:2] in (["issue"], ["pr"]) and w[2:3] in (["create"], ["comment"], ["edit"]):
            return True
        if w[:1] == ["git"] and _git_sub(w) == "commit":
            return True
    return False


def file_kind(path: str) -> str:
    """What a Read read: offloaded tool or task output, tests, or the file's type."""
    p = str(path or "")
    name = os.path.basename(p)
    if "/tool-results/" in p or ("/tasks/" in p and name.endswith(".output")):
        return "tool output"
    ext = os.path.splitext(name)[1].lower()
    if ext == ".py" and (name.startswith("test_") or name.endswith("_test.py") or "/tests/" in p):
        return "tests"
    return _KINDS.get(ext, "other")


def output_class(name: str, inp: dict, edited_later: bool) -> str:
    if name == "Bash":
        return bash_class(str(inp.get("command") or ""))
    if name == "Read":
        return f"Read {file_kind(inp.get('file_path'))}, {'edited later' if edited_later else 'never edited'}"
    if name.startswith(KB_PREFIX):
        return "KB " + name[len(KB_PREFIX):]
    return cr.display_name(name)


def own_block(b: dict) -> tuple[str, int] | None:
    """(class, tokens) of a block Claude wrote, carried into its stream's later calls like a result."""
    if b.get("type") == "text":
        return "own text", len(b.get("text") or "") // 4
    if b.get("type") != "tool_use":
        return None
    name, inp = str(b.get("name") or "?"), b.get("input") if isinstance(b.get("input"), dict) else {}
    if name == "Bash":
        cmd = str(inp.get("command") or "")
        return ("own issue/PR/commit body" if is_body(cmd) else "own Bash command"), len(cmd) // 4
    if name == "Write":
        kind = "tests" if file_kind(inp.get("file_path")) == "tests" else "source"
        return f"own Write {kind}", len(str(inp.get("content") or "")) // 4
    if name == "Edit":
        return "own Edit", (len(str(inp.get("old_string") or "")) + len(str(inp.get("new_string") or ""))) // 4
    return f"own {cr.display_name(name)} input", len(json.dumps(inp, ensure_ascii=False)) // 4


def _blocks(rec: dict) -> list:
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
    return [b for b in msg.get("content") if isinstance(b, dict)] if isinstance(msg.get("content"), list) else []


def _look_ahead(recs: list[dict]) -> tuple[dict, dict, dict]:
    """Last record index of each edited path, of each '#id' Claude wrote, and of each get_entry (type, id)."""
    edits, nums, entries = {}, {}, {}
    for i, rec in enumerate(recs):
        if rec.get("type") != "assistant":
            continue
        for b in _blocks(rec):
            if b.get("type") == "text":
                said = str(b.get("text") or "")
            elif b.get("type") == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                said = json.dumps(inp, ensure_ascii=False)
                name = str(b.get("name") or "")
                if name in session_cut.EDITS and (p := inp.get("file_path") or inp.get("notebook_path")):
                    edits[os.path.normpath(str(p))] = i
                if name == KB_PREFIX + "get_entry":
                    entries[(str(inp.get("entity_type")), str(inp.get("entry_id")))] = i
            else:
                continue
            for n in _REF.findall(said):
                nums[n] = i
    return edits, nums, entries


def _hits(text: str, at: int, nums: dict, entries: dict) -> tuple[int, list[int]]:
    """(hits shown, 1-based positions of those referenced after record `at`)."""
    shown = _HIT.findall(text)
    used = [pos for pos, (kind, n) in enumerate(shown, 1)
            if nums.get(n, -1) > at or entries.get((kind.split("/")[0].lower(), n), -1) > at]
    return len(shown), used


def _walk(recs, usage, since, until, seen, acc) -> int:
    """One stream: results, hook context and Claude's own blocks stay in context until a compaction."""
    edits, nums, entries = _look_ahead(recs)
    uses, live, counted, compactions = {}, [], set(), 0

    def enter(cls, kind, tokens, inside):
        if inside:
            row = acc["rows"][cls]
            row["kind"] = kind
            row["results"] += 1
            row["entered"] += tokens
            row["results_1k"] += tokens >= BIG
        live.append((cls, tokens))

    for i, rec in enumerate(recs):
        at = cr._epoch(rec.get("timestamp")) or 0.0
        inside = since <= at < until
        kind = rec.get("type")
        if kind == "system" and rec.get("subtype") == "compact_boundary":
            live.clear()
            compactions += 1
            continue
        att = rec.get("attachment") if isinstance(rec.get("attachment"), dict) else {}
        if kind == "attachment" and att.get("type") == "hook_additional_context":
            enter(f"hook {att.get('hookEvent') or '?'}", "output",
                  len("".join(map(str, att.get("content") or ()))) // 4, inside)
            continue
        if kind == "assistant":
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            mid = msg.get("id") or rec.get("uuid")
            if mid in usage and mid not in counted:
                counted.add(mid)
                if inside:
                    acc["input"] += usage[mid].tokens_in
                    acc["api_calls"] += 1
                    for cls, tokens in live:
                        acc["rows"][cls]["carried"] += tokens
                        acc["rows"][cls]["carried_1k"] += tokens if tokens >= BIG else 0
            for j, b in enumerate(_blocks(rec)):
                key = ("use", b.get("id")) if b.get("type") == "tool_use" else ("block", mid, j)
                if b.get("type") == "tool_use":
                    uses[b.get("id")] = (str(b.get("name") or "?"), b.get("input") or {}, i)
                if key in seen or (own := own_block(b)) is None:
                    continue
                seen.add(key)
                enter(own[0], "own", own[1], inside)
        elif kind == "user":
            for b in _blocks(rec):
                uid = b.get("tool_use_id")
                if b.get("type") != "tool_result" or ("result", uid) in seen:
                    continue
                seen.add(("result", uid))
                name, inp, _ = uses.get(uid, ("?", {}, i))
                inp = inp if isinstance(inp, dict) else {}
                path = os.path.normpath(str(inp.get("file_path") or "")) if name == "Read" else ""
                text = cr.result_text(b.get("content"))
                cls = output_class(name, inp, edits.get(path, -1) > i)
                enter(cls, "output", len(text) // 4, inside)
                if inside and name == KB_PREFIX + "search":
                    shown, used = _hits(text, i, nums, entries)
                    acc["searches"].append({"at": at, "tokens": len(text) // 4, "shown": shown,
                                            "referenced": len(used), "positions": used})
    return compactions


def _kb(searches: list[dict]) -> dict:
    big = [s for s in searches if s["tokens"] >= BIG]
    used = [p for s in big for p in s["positions"]]
    return {"searches": len(big), "hits": sum(s["shown"] for s in big), "referenced": len(used),
            "unreferenced_searches": sum(1 for s in big if not s["referenced"]),
            "at_6_or_later": sum(1 for p in used if p >= 6)}


def carried(root: Path, *, since: float | None = None, until: float | None = None, main_only: bool = False,
            referenced: bool = False) -> dict:
    """Carried context per class of tool output and of Claude's own blocks, with KB hit use when `referenced`."""
    since, until = since or 0.0, until if until is not None else float("inf")
    acc = {"input": 0, "api_calls": 0, "streams": 0, "compactions": 0, "searches": [],
           "rows": defaultdict(lambda: {"kind": "output", "results": 0, "entered": 0, "carried": 0,
                                        "results_1k": 0, "carried_1k": 0})}
    seen: set = set()
    for rs, usage in cr.streams(root, since, main_only):
        acc["streams"] += 1
        acc["compactions"] += _walk(rs, usage, since, until, seen, acc)
    total = acc["input"]
    rows = [{"class": c, **v, "share": round(v["carried"] / total, 4) if total else 0.0}
            for c, v in acc["rows"].items() if v["results"] or v["carried"]]
    rows.sort(key=lambda r: (r["kind"] != "output", -r["carried"], r["class"]))
    out = {k: acc[k] for k in ("input", "api_calls", "streams", "compactions")}
    out["rows"] = rows
    out["carried"] = sum(r["carried"] for r in rows if r["kind"] == "output")
    out["own_carried"] = sum(r["carried"] for r in rows if r["kind"] == "own")
    reads = [r for r in rows if r["class"].startswith("Read ")]
    out["reads"] = {"over_1k": sum(r["results_1k"] for r in reads),
                    "never_edited": sum(r["results_1k"] for r in reads if r["class"].endswith("never edited")),
                    "never_edited_carried_1k": {r["class"][5:].rsplit(",", 1)[0]: r["carried_1k"]
                                                for r in reads if r["class"].endswith("never edited")}}
    if referenced:
        out["kb"] = _kb(acc["searches"])
        out["searches"] = acc["searches"]
    return out
