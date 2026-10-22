"""A Claude Code session cut just before the agent's first edit of a file the fix changes: a repo case's prompt. #1095."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

#: Bytes the rendered conversation may take; the opening turn and the latest entries are kept.
BUDGET_BYTES = 24000
#: Bytes one tool output may take; a read or search is cut to this, any other output over it loses its body.
OUTPUT_CAP_BYTES = 1500
#: Bytes an output that is not a read or search may keep; past it, the body goes, since a command's output can carry
#: other people's words (a chat archive's rows) that no file the repo holds does.
COMMAND_CAP_BYTES = 400
#: An added line shorter than this ("return x", ")") is too common to count as the fix leaking.
LEAK_MIN_CHARS = 16
READS = ("Read", "Grep", "Glob", "LS", "NotebookRead")
EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
HEAD = ("Below is a Claude Code session, cut just before the agent's first edit to the code. "
        "Make the change the session is heading toward.\n\n")
_REMINDER = re.compile(r"<system-reminder>.*?(?:</system-reminder>|\Z)", re.S)
_WRITE = re.compile(r"sed\s+-i|perl\s+-[a-z]*i|(?<![<>2&-])>{1,2}\s*[\w./~$\"']|\btee\b|write_(?:text|bytes)|"
                    r"open\([^)]*[\"'][wax]|\b(?:cp|mv|rm|patch|apply_patch)\s|"
                    r"git\s+(?:apply|checkout|restore|stash|cherry-pick|merge|rebase|reset|am)\b")
_READ_BASH = re.compile(r"(?:^|&&|;|\|)\s*(?:cat|head|tail|sed\s+-n|grep|rg|ls|wc|find|tree|"
                        r"git\s+(?:diff|show|log|status|grep|blame|ls-files))\b")


@dataclass(frozen=True)
class Event:
    at: float
    kind: str
    name: str = ""
    body: str = ""
    input: dict | None = None


def _clean(text: str) -> str:
    return _REMINDER.sub("", text or "").strip()


def _text(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text") or "")
    return "\n".join(out)


def events(recs, user_text, ts) -> list[Event]:
    """One stream's user turns, assistant text, tool calls and their outputs, in order; `user_text(rec)` says what a person or parent typed."""
    out, names = [], {}
    for rec in recs:
        at = ts(rec.get("timestamp"))
        content = (rec.get("message") or {}).get("content")
        if rec.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and _clean(b.get("text")):
                    out.append(Event(at, "text", body=_clean(b.get("text"))))
                elif b.get("type") == "tool_use":
                    names[b.get("id")] = b.get("name") or ""
                    out.append(Event(at, "call", b.get("name") or "", input=dict(b.get("input") or {})))
        elif rec.get("type") == "user":
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        out.append(Event(at, "result", names.get(b.get("tool_use_id"), ""),
                                         _clean(_text(b.get("content")))))
            else:
                said = user_text(rec)
                if said and _clean(said):
                    out.append(Event(at, "user", body=_clean(said)))
    return out


def _mentions(command: str, rel: str) -> bool:
    return rel in command or bool(re.search(rf"(?<![\w.-]){re.escape(Path(rel).name)}(?![\w-])", command))


def edits(e: Event, files) -> bool:
    """Whether a tool call may change one of `files` (paths from the repo root); a doubtful shell command counts, so a cut errs early."""
    if e.kind != "call":
        return False
    args = e.input or {}
    if e.name in EDITS:
        path = str(args.get("file_path") or args.get("notebook_path") or "")
        return any(path == rel or path.endswith("/" + rel) for rel in files)
    if e.name == "Bash":
        cmd = str(args.get("command") or "")
        return any(_mentions(cmd, rel) for rel in files) and bool(_WRITE.search(cmd))
    return False


def first_edit(evs: list[Event], files, after: float = 0.0) -> int | None:
    """Index of the first call at or after `after` that edits one of `files`, or None."""
    return next((i for i, e in enumerate(evs) if e.at >= after and edits(e, files)), None)


def _cap(body: str, cap: int) -> str:
    """`body` cut to `cap` bytes at a word boundary, so no fragment reads as a word of its own."""
    raw = body.encode("utf-8")
    if len(raw) <= cap:
        return body
    head = raw[:cap].decode("utf-8", "ignore")
    head = head[:max(head.rfind(" "), head.rfind("\n"))] if " " in head or "\n" in head else head
    return head + f"\n[... {len(raw) - len(head.encode('utf-8'))} more bytes]"


def _call(e: Event, cap: int) -> str:
    a = e.input or {}
    if e.name in ("Read", "NotebookRead"):
        return f"## tool {e.name} {a.get('file_path') or a.get('notebook_path') or ''}".rstrip()
    if e.name in ("Grep", "Glob"):
        return f"## tool {e.name} {a.get('pattern', '')} {a.get('path', '')}".rstrip()
    if e.name == "Bash":
        return f"## tool Bash\n$ {_cap(str(a.get('command') or ''), cap)}"
    if e.name in EDITS:
        body = a.get("new_string") if "new_string" in a else a.get("content") or json.dumps(a.get("edits") or "")
        return f"## tool {e.name} {a.get('file_path', '')}\n{_cap(str(body or ''), cap)}"
    return f"## tool {e.name}\n{_cap(json.dumps(a, ensure_ascii=False), 200)}"


def _result(e: Event, call: Event | None, cap: int) -> str:
    size = len(e.body.encode("utf-8"))
    if e.name.startswith("mcp__") or e.name in ("Agent", "Task", "WebFetch", "WebSearch"):
        return f"[{size} bytes of output not shown]"
    read = e.name in READS or (e.name == "Bash" and call is not None
                               and _READ_BASH.search(str((call.input or {}).get("command") or "")))
    if read:
        return _cap(e.body, cap)
    if size <= min(cap, COMMAND_CAP_BYTES):
        return e.body
    return f"[{size} bytes of output not shown]"


def render(evs: list[Event], budget: int = BUDGET_BYTES, cap: int = OUTPUT_CAP_BYTES) -> str:
    """The events as one text: the first entry always, then as many of the latest as fit in `budget` bytes."""
    entries, last_call = [], None
    for e in evs:
        if e.kind == "user":
            entries.append(f"## user\n{_cap(e.body, cap * 4)}")
        elif e.kind == "text":
            entries.append(f"## assistant\n{_cap(e.body, cap * 2)}")
        elif e.kind == "call":
            last_call = e
            entries.append(_call(e, cap))
        elif e.kind == "result":
            entries[-1:] = [(entries[-1] + "\n" if entries else "") + _result(e, last_call, cap)]
    if not entries:
        return ""
    size = lambda s: len(s.encode("utf-8")) + 2  # noqa: E731
    head, kept, used = entries[0], [], size(entries[0])
    for entry in reversed(entries[1:]):
        if used + size(entry) > budget:
            break
        kept.append(entry)
        used += size(entry)
    gone = len(entries) - 1 - len(kept)
    return "\n\n".join([head, *([f"[... {gone} earlier entries not shown ...]"] if gone else []), *reversed(kept)])


def added_lines(diff: str, base_texts: dict) -> list[str]:
    """Lines the reference diff adds that its file did not hold at base, long enough to mean something."""
    out, path = [], ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("+") and not line.startswith("+++"):
            body = line[1:].strip()
            if len(body) >= LEAK_MIN_CHARS and body not in base_texts.get(path, ""):
                out.append(body)
    return sorted(set(out))


def leaks(prompt: str, lines) -> list[str]:
    """The added lines a prompt already holds: a cut that shows the fix."""
    return [line for line in lines if line in prompt]
