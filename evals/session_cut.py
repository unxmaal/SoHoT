"""A Claude Code session cut just before the agent's first edit of a file the fix changes: a repo case's prompt. #1095."""
from __future__ import annotations

import json
import re
import shlex
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
#: What a script fed to an interpreter calls to write a file.
_SCRIPT_WRITE = re.compile(r"write_(?:text|bytes)\(|open\([^)]*,\s*(?:mode\s*=\s*)?[\"'][wax]|\.write\(|"
                           r"shutil\.(?:copy\w*|move)\(|os\.(?:replace|rename|remove|unlink)\(|\.(?:unlink|rename)\(|"
                           r"writeFileSync|File\.write")
_INTERPRETER = re.compile(r"(?:^|\s|/)(?:python[\d.]*|node|ruby|perl|bash|sh|zsh)(?:\s|$)")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n(.*?)(?:\n[ \t]*\2[ \t]*(?=\n|$)|\Z)", re.S)
_REDIRECT = (">", ">>", "&>", "&>>", ">|")
_ISSUE_VIEW = re.compile(r"\bgh\s+issue\s+view\s+(?:https://github\.com/([\w.-]+)/([\w.-]+)/issues/)?#?(\d+)\b")
_READ_BASH = re.compile(r"(?:^|&&|;|\|)\s*(?:cat|head|tail|sed\s+-n|grep|rg|ls|wc|find|tree|"
                        r"git\s+(?:diff|show|log|status|grep|blame|ls-files))\b")


@dataclass(frozen=True)
class Event:
    at: float
    kind: str
    name: str = ""
    body: str = ""
    input: dict | None = None
    ref: str = ""
    cwd: str = ""


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
        at, cwd = ts(rec.get("timestamp")), str(rec.get("cwd") or "")
        content = (rec.get("message") or {}).get("content")
        if rec.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and _clean(b.get("text")):
                    out.append(Event(at, "text", body=_clean(b.get("text"))))
                elif b.get("type") == "tool_use":
                    names[b.get("id")] = b.get("name") or ""
                    out.append(Event(at, "call", b.get("name") or "", input=dict(b.get("input") or {}),
                                     ref=str(b.get("id") or ""), cwd=cwd))
        elif rec.get("type") == "user":
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        out.append(Event(at, "result", names.get(b.get("tool_use_id"), ""),
                                         _clean(_text(b.get("content"))), ref=str(b.get("tool_use_id") or "")))
            else:
                said = user_text(rec)
                if said and _clean(said):
                    out.append(Event(at, "user", body=_clean(said)))
    return out


def _mentions(command: str, rel: str) -> bool:
    return rel in command or bool(re.search(rf"(?<![\w.-]){re.escape(Path(rel).name)}(?![\w-])", command))


def _names(token: str, rel: str) -> bool:
    token = token.strip("\"'").removeprefix("./")
    return bool(token) and (token == rel or token.endswith("/" + rel) or rel.endswith("/" + token))


def _segments(shell: str) -> list[str]:
    """`shell` split into simple commands at ;, &&, ||, | and newlines outside quotes."""
    out, cur, quote, i = [], [], None, 0
    while i < len(shell):
        c = shell[i]
        if quote:
            if c == "\\" and quote == '"':
                cur.append(shell[i:i + 2])
                i += 2
                continue
            quote = None if c == quote else quote
        elif c in "'\"":
            quote = c
        elif c == "\\":
            cur.append(shell[i:i + 2])
            i += 2
            continue
        elif c in ";\n|" or shell.startswith("&&", i):
            out.append("".join(cur))
            cur = []
            i += 2 if shell.startswith(("&&", "||"), i) else 1
            continue
        cur.append(c)
        i += 1
    return [seg.strip() for seg in [*out, "".join(cur)] if seg.strip()]


def _targets(seg: str) -> list[str] | None:
    """The paths one simple command may write, or None when it cannot be read as words."""
    try:
        words = list(shlex.shlex(seg, posix=True, punctuation_chars=True))
    except ValueError:
        return None
    out = [words[k + 1] for k, w in enumerate(words[:-1]) if w in _REDIRECT]
    args = [w for w in words if "=" not in w or w.startswith("-")]
    while args and args[0] in ("sudo", "env", "command", "time", "xargs", "nohup"):
        args = args[1:]
    if not args:
        return out
    cmd, rest = Path(args[0]).name, [w for w in args[1:] if not w.startswith("-") and w not in _REDIRECT]
    flags = [w for w in args[1:] if w.startswith("-") and not w.startswith("--")]
    if cmd == "tee" or cmd in ("rm", "unlink", "truncate", "touch"):
        out += rest
    elif cmd in ("sed", "gsed", "perl") and (any("i" in f for f in flags) or "--in-place" in args):
        out += rest
    elif cmd in ("cp", "mv", "install", "ln", "rsync") and rest:
        out.append(rest[-1])
    elif cmd == "git":
        sub = next((w for k, w in enumerate(args[1:], 1) if not w.startswith("-") and args[k - 1] not in ("-C", "-c")),
                   "")
        if sub in ("checkout", "restore", "rm", "mv", "apply", "am"):
            out += rest
    elif cmd in ("patch", "apply_patch"):
        out += rest
    return out


def writes(command: str, rel: str) -> bool:
    """Whether a shell command may write `rel`: a redirect, tee, sed -i, cp or git checkout naming it, or a script fed to
    an interpreter that names it and writes a file; a command that cannot be read counts when it names it."""
    for m in _HEREDOC.finditer(command):
        line = command[command.rfind("\n", 0, m.start()) + 1:m.start()]
        body = m.group(3)
        if re.search(r"(?:^|\s)(?:bash|sh|zsh)(?:\s|$)", line) and writes(body, rel):
            return True
        if _INTERPRETER.search(line) and _mentions(body, rel) and _SCRIPT_WRITE.search(body):
            return True
        if re.search(r"\b(?:git\s+apply|patch|apply_patch)\b", line) and _mentions(body, rel):
            return True
    shell = _HEREDOC.sub(lambda m: m.group(0)[:m.start(3) - m.start()], command)
    for seg in _segments(shell):
        got = _targets(seg)
        if got is None:
            if _mentions(seg, rel) and _WRITE.search(seg):
                return True
        elif any(_names(t, rel) for t in got):
            return True
        if re.search(r"\s-[ce]\s", f" {seg} ") and _INTERPRETER.search(seg) and _mentions(seg, rel) \
                and _SCRIPT_WRITE.search(seg):
            return True
    return False


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
        return any(writes(cmd, rel) for rel in files)
    return False


def views_issue(e: Event, owner: str, name: str) -> bool:
    """Whether a call is `gh issue view` of an issue of owner/name, by --repo, the issue's URL or the directory it ran in."""
    if e.kind != "call" or e.name != "Bash":
        return False
    cmd, here = str((e.input or {}).get("command") or ""), e.cwd
    for seg in _segments(cmd):
        if re.match(r"cd\s", seg):
            here = seg[3:].strip().strip("\"'")
        m = _ISSUE_VIEW.search(seg)
        if not m or "--comments" in seg:
            continue
        flag = re.search(r"(?:-R|--repo)[\s=]+(?:https://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?(?:\s|$)", seg)
        repo = (m.group(1), m.group(2)) if m.group(1) else (flag.group(1), flag.group(2)) if flag else None
        if repo is not None:
            if repo[0].lower() == owner.lower() and repo[1].lower() == name.lower():
                return True
        elif re.fullmatch(rf"{re.escape(name.lower())}(?:-[\w.-]+)?", Path(here.rstrip("/")).name.lower() or "-"):
            return True
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


def _result(e: Event, call: Event | None, cap: int, whole: bool = False) -> str:
    size = len(e.body.encode("utf-8"))
    if whole:
        return e.body
    if e.name.startswith("mcp__") or e.name in ("Agent", "Task", "WebFetch", "WebSearch"):
        return f"[{size} bytes of output not shown]"
    read = e.name in READS or (e.name == "Bash" and call is not None
                               and _READ_BASH.search(str((call.input or {}).get("command") or "")))
    if read:
        return _cap(e.body, cap)
    if size <= min(cap, COMMAND_CAP_BYTES):
        return e.body
    return f"[{size} bytes of output not shown]"


def render(evs: list[Event], budget: int = BUDGET_BYTES, cap: int = OUTPUT_CAP_BYTES, pin=None) -> str:
    """The events as one text: the opening user turns always, then each call `pin` names with its whole output, then as
    many of the latest entries as fit in `budget` bytes."""
    entries, pinned, at, calls = [], set(), {}, {}
    for e in evs:
        if e.kind == "user":
            entries.append(f"## user\n{_cap(e.body, cap * 4)}")
        elif e.kind == "text":
            entries.append(f"## assistant\n{_cap(e.body, cap * 2)}")
        elif e.kind == "call":
            at[e.ref or len(entries)], calls[len(entries)] = len(entries), e
            if pin is not None and pin(e):
                pinned.add(len(entries))
            entries.append(_call(e, cap))
        elif e.kind == "result":
            k = at.get(e.ref, len(entries) - 1) if e.ref else len(entries) - 1
            if k < 0:
                continue
            entries[k] = entries[k] + "\n" + _result(e, calls.get(k), cap, k in pinned and e.name == "Bash")
    if not entries:
        return ""
    size = lambda s: len(s.encode("utf-8")) + 2  # noqa: E731
    lead = next((k for k, entry in enumerate(entries) if not entry.startswith("## user\n")), len(entries)) or 1
    keep = set(range(lead)) | pinned
    used = sum(size(entries[k]) for k in keep)
    for k in range(len(entries) - 1, lead - 1, -1):
        if k in keep:
            continue
        if used + size(entries[k]) > budget:
            break
        keep.add(k)
        used += size(entries[k])
    out, gone = [], 0
    for k, entry in enumerate(entries):
        if k not in keep:
            gone += 1
            continue
        if gone:
            out.append(f"[... {gone} earlier entries not shown ...]")
            gone = 0
        out.append(entry)
    return "\n\n".join(out)


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


def _entries(text: str) -> list[str]:
    out = []
    for part in re.split(r"\n\n(?=## )", text):
        if out and not part.startswith(("## user\n", "## assistant\n", "## tool ")):
            out[-1] += "\n\n" + part
        else:
            out.append(part)
    return out


def on_task(text: str, issues, files) -> bool:
    """Whether a rendered cut heads toward the fix: a user turn names or a `gh issue view` shows one of the fix's
    `issues`; for a fix that names none, a user turn names or a call reads one of the `files` it changes."""
    issues = sorted({str(n) for n in issues})
    entries = _entries(text)
    if issues:
        named = re.compile(rf"(?:#|/issues/|\bissues?\s+)(?:{'|'.join(issues)})\b", re.I)
        return any(named.search(e) for e in entries if e.startswith("## user\n")) or any(
            m.group(3) in issues for e in entries if e.startswith("## tool Bash\n")
            for m in _ISSUE_VIEW.finditer(e.split("\n", 2)[1]))
    for e in entries:
        head, _, rest = e.partition("\n")
        if head == "## user" and any(_mentions(rest, rel) for rel in files):
            return True
        if head.startswith(("## tool Read ", "## tool Grep ", "## tool Glob ")):
            if any(_names(w, rel) for w in head.split()[3:] for rel in files):
                return True
        elif head == "## tool Bash":
            cmd = rest.split("\n", 1)[0].removeprefix("$ ")
            if _READ_BASH.search(cmd) and any(_mentions(cmd, rel) for rel in files):
                return True
    return False
