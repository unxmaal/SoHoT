"""An exploratory read as quoted spans with line numbers, picked by a local model and checked line by line against the file. #1336."""
from __future__ import annotations

import os
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from harness import cuts, delegate

#: About 1k tokens at chars/4: a shorter file is returned whole, with no call.
MIN_CHARS = 4000
#: Characters of numbered file per call: about 8k tokens at delegate.CHARS_PER_TOKEN.
CHUNK_CHARS = 24_000
#: Local reply budget; quoting the first and last line of each span keeps most replies far under it.
REPLY_TOKENS = 2048
#: Spans quoting more than this share of the file save too little; the file goes back whole.
MAX_SHARE = 0.5
#: Shortest anchor accepted unless it is the whole line.
ANCHOR_CHARS = 12
#: A full Read of a spanned path this many tool calls later counts as a redo.
REDO_WINDOW = 10
SPANS, WHOLE = "spans", "whole"
SYSTEM = ("You pick the lines of a file that answer an engineer's question. Each line of the file is shown "
          "as its line number, '|', then the line. Reply with one line per span and nothing else:\n"
          "@@ START-END | <the text of line START, copied exactly>\n"
          "For example:\n@@ 120-134 | def load(path: str) -> dict:\n@@ 301-301 | MAX_ROWS = 500\n"
          "Do not copy the rest of the span; the lines are read from the file. Pick only what answers the "
          "question: the signatures, definitions, constants, steps or paragraphs asked about, at most about "
          "80 lines in all. If nothing in the text is relevant, reply with the single word: none. If the "
          "question cannot be answered without the whole file, reply with the single word: insufficient")
_HEAD = re.compile(r"^@@\s*(\d+)(?:\s*-\s*(\d+))?\s*(?:@@)?\s*(?:\|(.*))?$")
_SPANS_MODE = re.compile(r'"mode":\s*"spans"')
_CAT = re.compile(r"^\s*(\d+)\t(.*)$")


class Doubt(ValueError):
    """The reply cannot be trusted; `code` names why for the eval's tally."""

    def __init__(self, code: str, why: str):
        super().__init__(why)
        self.code = code


@dataclass
class Result:
    mode: str
    reason: str
    code: str
    body: str
    lines: int
    chars: int
    spans: list
    calls: int
    model: str
    seconds: float

    def header(self, name: str) -> str:
        if self.mode == SPANS:
            ranges = ", ".join(f"{a}-{b}" for a, b in self.spans)
            return (f"spans: {name} lines {ranges} of {self.lines}, quotes checked against the file; "
                    f"Read with offset/limit for more")
        return f"whole: {name}, {self.lines} lines ({self.reason})"


def parts(lines: list[str], size: int) -> list[tuple[int, int]]:
    """1-based (first, last) line ranges whose numbered text is at most about `size` characters each."""
    out, start, n = [], 1, 0
    for i, line in enumerate(lines, 1):
        cost = len(line) + 8
        if n and n + cost > size:
            out.append((start, i - 1))
            start, n = i, 0
        n += cost
    if lines:
        out.append((start, len(lines)))
    return out


def prompt(question: str, lines: list[str], first: int, last: int, name: str = "") -> str:
    numbered = "\n".join(f"{i}|{lines[i - 1]}" for i in range(first, last + 1))
    where = f"{name}, lines {first}-{last} of {len(lines)}" if name else f"lines {first}-{last} of {len(lines)}"
    return f"Question: {question.strip()}\n\n=== {where} ===\n{numbered}"


def _unfence(rows: list[str]) -> list[str]:
    """Drop the closing fence of a reply that opened one before its first span."""
    head = next((k for k, r in enumerate(rows) if _HEAD.match(r.strip())), len(rows))
    if not any(r.lstrip().startswith("```") for r in rows[:head]):
        return rows
    while rows and not rows[-1].strip():
        rows = rows[:-1]
    return rows[:-1] if rows and rows[-1].strip() == "```" else rows


def _blank_tail(rows: list[str]) -> list[str]:
    while rows and not rows[-1].strip():
        rows = rows[:-1]
    return rows


def _quote(body: list[str], a: int, b: int) -> list[str]:
    """The quoted lines; 'N|' prefixes are dropped when they number exactly the span or its first and last line."""
    body = _blank_tail(body)
    nums = [m.group(1) for m in (re.match(r"^(\d+)\|", line) for line in body) if m]
    if body and len(nums) == len(body) and [int(n) for n in nums] in (list(range(a, a + len(body))), [a, b]):
        return [line[len(n) + 1:] for line, n in zip(body, nums)]
    return body


def matches(quoted: list[str], want: list[str]) -> bool:
    """The whole span, or its first and last line, exactly as the file has them; trailing blank lines carry nothing."""
    want = _blank_tail(want)
    if not quoted or not want:
        return False
    # The prompt shows a blank line as 'N|'; a quote that kept the bar is the same line.
    for q in (quoted, [x[1:] if x.startswith("|") else x for x in quoted]):
        if q == want or (len(want) > 2 and q == [want[0], want[-1]]):
            return True
    # A one-line anchor: line START's text verbatim, perhaps without its diff or Markdown marker, or cut short.
    first, line = quoted[0].strip(), want[0].strip()
    if len(quoted) != 1 or not first or first not in line:
        return False
    if len(first) < min(len(line), ANCHOR_CHARS):
        cuts.cut("harness/spans.py:ANCHOR_CHARS", "a span anchor too short to trust", kept=0, dropped=1)
        return False
    return True


def parse(reply: str, lines: list[str], first: int, last: int) -> list[tuple[int, int]]:
    """The spans a reply names inside lines first..last, each quote checked against the file; Doubt otherwise."""
    text = (reply or "").strip()
    rows = [r for r in text.splitlines() if r.strip()]
    heads = [r for r in rows if _HEAD.match(r.strip())]
    word = (text if heads else (rows[-1] if rows else "")).strip("`'\"*.:! ").lower()
    if word == "none":
        return []
    if word.startswith("insufficient"):
        raise Doubt("insufficient", "the model says the question needs the whole file")
    blocks, cur = [], None
    for row in _unfence(text.splitlines()):
        m = _HEAD.match(row.strip())
        if m:
            cur = (int(m.group(1)), int(m.group(2) or m.group(1)), [] if m.group(3) is None else [m.group(3)])
            blocks.append(cur)
        elif cur is not None:
            cur[2].append(row)
    if not blocks:
        raise Doubt("format", "the reply quotes no span")
    out = []
    for k, (a, b, body) in enumerate(blocks):
        if k and not _blank_tail(body) and blocks[k - 1][:2] == (a, b):
            continue  # a closing marker repeating the span's own header
        if not first <= a <= b <= last:
            raise Doubt("range", f"span {a}-{b} is outside lines {first}-{last}")
        if not matches(_quote(body, a, b), lines[a - 1:b]):
            raise Doubt("quote", f"the quote of {a}-{b} differs from the file")
        out.append((a, b))
    return out


def merge(spans) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def render(lines: list[str], spans) -> str:
    """The spans as Read shows a file: right-aligned number, tab, line; '...' between spans."""
    blocks = ["\n".join(f"{i:>6}\t{lines[i - 1]}" for i in range(a, b + 1)) for a, b in spans]
    return "\n   ...\n".join(blocks)


def verbatim(text: str, body: str) -> bool:
    """Every numbered line of `body` equals that line of `text`, byte for byte."""
    lines = text.splitlines()
    for row in body.splitlines():
        if row == "   ...":
            continue
        m = _CAT.match(row)
        if not m or not 1 <= int(m.group(1)) <= len(lines) or lines[int(m.group(1)) - 1] != m.group(2):
            return False
    return True


def answer(text: str, question: str, *, name: str = "", lane: str = "code", complete=None,
           max_tokens: int | None = None, size: int | None = None, model: str | None = None) -> Result:
    """Spans of `text` that answer `question`; the whole file on any doubt, refusal or failure."""
    lines = text.splitlines()
    started = time.perf_counter()
    calls, served = 0, ""

    def whole(code: str, reason: str) -> Result:
        return Result(WHOLE, reason, code, render(lines, [(1, len(lines))]) if lines else "", len(lines),
                      len(text), [], calls, served, round(time.perf_counter() - started, 4))
    if not (question or "").strip():
        return whole("question", "no question")
    if len(text) < MIN_CHARS:
        cuts.cut("harness/spans.py:MIN_CHARS", "a short file returned whole", kept=1, dropped=0)
        return whole("short", f"under {MIN_CHARS} characters")
    max_tokens = int(max_tokens or REPLY_TOKENS)
    complete = complete or delegate.complete
    ranges = parts(lines, int(size or CHUNK_CHARS))
    if len(ranges) > 1:
        cuts.cut("harness/spans.py:CHUNK_CHARS", f"a file asked in {len(ranges)} parts", kept=len(ranges), dropped=0)
    found = []
    for first, last in ranges:
        try:
            got = complete(lane, prompt(question, lines, first, last, name), system=SYSTEM,
                           max_tokens=max_tokens, thinking=False, **({"model": model} if model else {}))
        except Exception as exc:  # noqa: BLE001 - any failure means the whole file
            return whole("model", f"the local model failed: {exc}")
        calls += 1
        served = got.get("model") or served
        if (got.get("completion_tokens") or 0) >= max_tokens:
            cuts.cut("harness/spans.py:REPLY_TOKENS", "a spans reply reached its token budget", value=max_tokens,
                     kept=0, dropped=1)
            return whole("budget", "the reply reached its token budget")
        try:
            found += parse(got.get("text") or "", lines, first, last)
        except Doubt as d:
            return whole(d.code, str(d))
    spans = merge(found)
    if not spans:
        return whole("none", "the model found no lines that answer it")
    quoted = sum(len(lines[i - 1]) + 1 for a, b in spans for i in range(a, b + 1))
    if quoted > MAX_SHARE * len(text):
        cuts.cut("harness/spans.py:MAX_SHARE", "spans covering most of a file", value=MAX_SHARE, kept=0, dropped=1)
        return whole("share", f"the spans quote {quoted / len(text):.0%} of the file")
    return Result(SPANS, "", "", render(lines, spans), len(lines), len(text), spans, calls, served,
                  round(time.perf_counter() - started, 4))


def ask_file(raw, question: str, *, lane: str = "code", roots=None, cwd: Path | None = None,
             max_tokens: int | None = None, model: str | None = None, delegated: bool = False,
             complete=None) -> dict:
    """One file read inside #1335's roots (harness/ask.read), as spans or whole, in local_complete's shape."""
    from harness import ask, purpose
    if not (question or "").strip():
        raise ask.Refused("spans needs a question")
    files = ask.read(raw, ask.default_roots(cwd) if roots is None else roots, cwd)
    if len(files) != 1:
        raise ask.Refused(f"spans reads one file, not {len(files)}")
    f, replies, base = files[0], [], complete or delegate.complete

    def call(lane_: str, prompt_: str, **kw) -> dict:
        got = base(lane_, prompt_, tag=purpose.WORK if delegated else purpose.INTERNAL, **kw)
        replies.append(got)
        return got
    got = answer(f.text, question, name=f.path, lane=lane, complete=call, max_tokens=max_tokens, model=model)

    def total(key: str):
        counts = [r.get(key) for r in replies]
        return sum(counts) if counts and None not in counts else None
    out = {"text": got.header(f.path) + "\n" + got.body, "lane": lane, "mode": got.mode, "reason": got.reason,
           "spans": got.spans, "spec": replies[-1].get("spec", "") if replies else "", "model": got.model,
           "ttft_s": replies[0].get("ttft_s") if replies else None, "seconds": got.seconds,
           "prompt_tokens": total("prompt_tokens"), "completion_tokens": total("completion_tokens"),
           "method": None, "call_id": "", "files": [{"path": f.path, "bytes": f.size}],
           "parts": len(replies), "calls": got.calls}
    if delegated and replies:
        from harness import delegations
        out = delegations.note(out, delegations.new_id())
    return out


def spanned_path(command: str) -> str:
    """The path a `soh spans PATH` Bash command reads, or ""."""
    for seg in re.split(r"\s*(?:&&|\|\||;|\||\n)\s*", command or ""):
        try:
            words = shlex.split(seg)
        except ValueError:
            continue
        for k, w in enumerate(words[:-1]):
            if w == "spans" and k and os.path.basename(words[k - 1]) == "soh":
                rest, skip = words[k + 1:], False
                for x in rest:
                    if skip:
                        skip = False
                    elif x in ("-q", "--question", "--lane", "--max-tokens"):
                        skip = True
                    elif not x.startswith("-"):
                        return os.path.normpath(x)
    return ""


def redos(streams, window: int = REDO_WINDOW, since: float | None = None) -> dict:
    """Spans calls (soh spans, local_complete mode spans) that returned spans, and how many a full Read of the same path followed within `window` tool calls."""
    from harness.context_report import _epoch, result_text
    calls = redone = 0
    for recs in streams:
        uses, answered = [], {}
        for rec in recs:
            content = (rec.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    uses.append((str(b.get("id") or ""), str(b.get("name") or ""),
                                 b.get("input") if isinstance(b.get("input"), dict) else {}, _epoch(rec.get("timestamp"))))
                elif b.get("type") == "tool_result":
                    answered[str(b.get("tool_use_id") or "")] = result_text(b.get("content"))
        for i, (uid, name, given, at) in enumerate(uses):
            said = answered.get(uid, "")
            if name == "Bash":
                path, ok = spanned_path(str(given.get("command") or "")), said.lstrip().startswith("spans:")
            else:
                many = given.get("paths") if isinstance(given.get("paths"), list) else [given.get("paths")]
                path = os.path.normpath(str(many[0])) if name.endswith("local_complete") and many[0] else ""
                ok = given.get("mode") == "spans" and bool(_SPANS_MODE.search(said))
            if not path or not ok:
                continue
            if since is not None and (at is None or at < since):
                continue
            calls += 1
            for _, later, again, _ in uses[i + 1:i + 1 + window]:
                if (later == "Read" and os.path.normpath(str(again.get("file_path") or "")) == path
                        and again.get("offset") is None and again.get("limit") is None):
                    redone += 1
                    break
    return {"calls": calls, "redos": redone, "rate": (redone / calls) if calls else None}
