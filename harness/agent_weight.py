"""Per-subagent tokens spent reading and re-reading files before the first edit, from Claude Code transcripts, read only. #1260."""
from __future__ import annotations

import json
import posixpath
import re
import shlex
from pathlib import Path

#: A Read with no offset or limit, a cat: the whole file.
WHOLE = (1, float("inf"))
#: A tail: covered only by a whole read, and covers no range.
TAIL = (float("inf"), float("inf"))
#: Lines head shows when no -n is given.
HEAD_LINES = 10
_LABEL = re.compile(r"[A-Za-z][\w-]{0,39}")
_SED_RANGE = re.compile(r"(\d+)(?:,(\d+))?p")
#: Not an edit of the work: output thrown away or logged to a scratch file, and git moving between commits.
_NOT_EDITS = re.compile(r"\d?>>?\s*(?:/dev/null|\S*\btmp/\S*|\S+\.log)(?=\s|$|;|&|\|)|\d?>&\d|"
                        r"\bgit\s+(?:checkout|switch|restore|stash|cherry-pick|merge|rebase|reset|am|worktree)\b")


def label(meta: Path, known) -> str:
    """The subagent's agentType when it is a plain word with nothing to redact, else "other"."""
    from evals import redact
    try:
        kind = str(json.loads(meta.read_text(encoding="utf-8")).get("agentType") or "")
    except (OSError, ValueError, AttributeError):
        return "unknown"
    return kind if _LABEL.fullmatch(kind) and not redact.detect(kind, known) else "other"


def _norm(path: str, cwd: str) -> str:
    p = str(path).strip("\"'").replace("\\", "/")
    if not posixpath.isabs(p) and not re.match(r"[A-Za-z]:/", p):
        p = posixpath.join(cwd.replace("\\", "/") or "/", p)
    return posixpath.normpath(p)


def _bash_reads(command: str, cwd: str) -> list[tuple[str, tuple]]:
    """(path, line range) of each file a cat, head, tail or sed -n in `command` prints."""
    from evals import session_cut
    out = []
    for seg in session_cut._segments(command):
        try:
            words = shlex.split(seg)
        except ValueError:
            continue
        if not words:
            continue
        cmd, args = posixpath.basename(words[0]), words[1:]
        files, rng, script, skip = [], None, None, False
        for i, w in enumerate(args):
            if skip:
                skip = False
                continue
            if cmd in ("head", "tail") and w in ("-n", "-c"):
                skip, rng = True, (1, int(args[i + 1])) if i + 1 < len(args) and args[i + 1].isdigit() else None
            elif w.startswith("-"):
                continue
            elif cmd == "sed" and script is None:
                script = w
            else:
                files.append(w)
        if cmd == "cat":
            rng = WHOLE
        elif cmd == "head":
            rng = rng or (1, HEAD_LINES)
        elif cmd == "tail":
            rng = TAIL
        elif cmd == "sed" and "-n" in args and script and (m := _SED_RANGE.fullmatch(script)):
            rng = (int(m.group(1)), int(m.group(2) or m.group(1)))
        else:
            continue
        out += [(_norm(f, cwd), rng) for f in files]
    return out


def _writes(command: str) -> bool:
    from evals import session_cut
    shell = session_cut._HEREDOC.sub(lambda m: m.group(0)[:m.start(3) - m.start()], command)
    return bool(session_cut._WRITE.search(_NOT_EDITS.sub(" ", shell)))


def _read_range(args: dict) -> tuple:
    off, lim = args.get("offset"), args.get("limit")
    if off is None and lim is None:
        return WHOLE
    start = int(off or 1)
    return (start, start + int(lim) - 1) if lim else (start, float("inf"))


def stream(recs: list[dict], usage: dict, claimed_tools: set) -> dict:
    """One subagent stream's input tokens, and its read, re-read and carried tokens before its first edit.
    `usage` holds this stream's own messages (copies counted elsewhere left out); `claimed_tools` the tool_use ids
    another stream holds, which grows by this stream's."""
    from harness import context_report as cr
    calls, reads, order, edited = {}, [], [], False
    for i, rec in enumerate(recs):
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        content = msg.get("content")
        if rec.get("type") == "assistant":
            mid = msg.get("id") or rec.get("uuid")
            if mid in usage and mid not in order:
                order.append(mid)
            for b in content if isinstance(content, list) else ():
                if not isinstance(b, dict) or b.get("type") != "tool_use" or b.get("id") in claimed_tools:
                    continue
                claimed_tools.add(b.get("id"))
                if edited:
                    continue
                name, args, cwd = str(b.get("name") or ""), dict(b.get("input") or {}), str(rec.get("cwd") or "")
                from evals import session_cut
                if name in session_cut.EDITS or (name == "Bash" and _writes(str(args.get("command") or ""))):
                    edited = True
                elif name == "Read" and args.get("file_path"):
                    calls[b.get("id")] = [(_norm(args["file_path"], cwd), _read_range(args))]
                elif name == "Bash" and (got := _bash_reads(str(args.get("command") or ""), cwd)):
                    calls[b.get("id")] = got
        elif rec.get("type") == "user" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                    reads.append((calls.pop(b.get("tool_use_id")), len(cr.result_text(b.get("content"))) // 4,
                                  len(order)))
    seen: dict = {}
    out = {"messages": len(order), "input": sum(usage[m].tokens_in for m in order), "read": 0, "reread": 0,
           "carried": 0, "carried_reread": 0, "edited": edited}
    for files, tokens, before in reads:
        again = all(any(a <= r[0] and r[1] <= b for a, b in seen.get(p, ())) for p, r in files)
        later = len(order) - before
        out["read"] += tokens
        out["carried"] += tokens * later
        if again:
            out["reread"] += tokens
            out["carried_reread"] += tokens * later
        for p, r in files:
            seen.setdefault(p, []).append(r)
    return out


def scan(root: Path | None = None, since: float = 0.0, now: float | None = None, known=None) -> list[dict]:
    """One row per subagent that began in [since, now]: its id, agent type, and stream()'s counts."""
    import time

    from evals import redact
    from evals.analysis import demand
    from evals.importers import transcripts as tr
    from harness import context_report as cr
    root = Path(root or cr.default_root())
    now = time.time() if now is None else now
    known = redact.known_here() if known is None else known
    out = []
    for _project, main, subs in tr.sessions(root):
        if not subs or main.stat().st_mtime < since:
            continue
        recs = [r for r in tr.records(main) if not r.get("isSidechain")]
        if demand._headless(recs):
            continue
        claimed = set(demand._usage(recs))
        tools = {b.get("id") for r in recs if isinstance(r.get("message"), dict)
                 for b in (r["message"].get("content") if isinstance(r["message"].get("content"), list) else ())
                 if isinstance(b, dict) and b.get("type") == "tool_use"}
        sub_recs = sorted(((s, list(tr.records(s))) for s in subs), key=lambda kv: (demand._began(kv[1]), kv[0].stem))
        for s, rs in sub_recs:
            usage = demand._usage(rs, claimed)
            claimed |= set(usage)
            began = demand._began(rs)
            got = stream(rs, usage, tools)
            if since <= began <= now:
                out.append({"id": s.stem, "type": label(s.with_name(s.stem + ".meta.json"), known), "began": began,
                            **got})
    return out
