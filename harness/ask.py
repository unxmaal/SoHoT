"""A question about files on this machine, answered by a lane's local model from the files it reads itself. #1335."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from harness import cuts, delegate, purpose

Refused = delegate.Refused

#: Extra roots the server may read, os.pathsep-separated; a caller's worktree goes here for the MCP server.
ROOTS_ENV = "SOHOT_ASK_ROOTS"
CLAUDE_ENV = "CLAUDE_CONFIG_DIR"
MAX_BYTES = 1 << 20
MAX_PATHS = 16
#: Characters of file per call; 24,000 found half the plants on the extract lane, 8,000 four in five (#1335).
CHUNK_CHARS = 8_000
#: The issue's digest budget: a reply of at most about 500 tokens.
REPLY_TOKENS = 600
NONE = "none"
#: A full Read of a digested path this many tool calls later counts as a redo.
REDO_WINDOW = 10
SYSTEM = ("You read logs and tool output for an engineer who will not read them. Answer the question "
          "from the text alone. Quote test names, error lines and counts exactly as the text has them, "
          "one per line, with no preamble. In test and build logs a failure is a FAILED or ERROR test, "
          "an exception or Traceback line, an ##[error] line, a nonzero count of errors or failures, or "
          "a nonzero exit; PASSED, SKIPPED, XFAIL, XPASS, warnings, retries and 0 errors are not "
          "failures. If the text does not contain an answer, reply with the single word: none")
MERGE = ("Each note below answers the question for one part of the same files. Combine them into one "
         "answer: keep every distinct name, line and count exactly as written, drop repeats, add nothing. "
         "If no note holds an answer, reply with the single word: none")
_NONE_WORDS = {"none", "not found", "none found", "nothing", "n/a", "no"}
#: Status words of a line that did not fail, dropped from an answer to a question about failures.
_NOT_FAILING = re.compile(r"\b(PASSED|SKIPPED|XFAIL|XPASS|DeprecationWarning)\b")
_ABOUT_FAILURE = re.compile(r"\b(fail|error|broke|traceback|exception|wrong)", re.I)
_CALM_COUNT = re.compile(r"\b\d+ (?:passed|skipped|xfailed|xpassed|deselected|warnings?|ignored)\b", re.I)
_FAILING_WORD = re.compile(r"\b(?:fail\w*|errors?|exception|traceback|panic\w*)\b", re.I)
#: Failure-shaped lines a scan adds to a failure answer; a small model skips count and exception lines (#1335).
FAILURE_LINES = 20
#: Characters kept of a failure-shaped line, around its match.
LINE_CHARS = 300
_STAMP = re.compile(r"^\s*(?:\d{4}-\d\d-\d\d[T ][\d:.,]+Z?|\[?\d\d:\d\d:\d\d[\d.,]*\]?)\s+")
_FAILURE = (
    re.compile(r"(?<![\w.,])[1-9]\d*\s+(?:errors?|failed|failures?|failing|broken)\b", re.I),
    re.compile(r"(?<!expected )\b(?:errors?|failures?|failed)\s*[=:]\s*[1-9]", re.I),
    re.compile(r"(?:^|\s)(?:FAILED|FAIL|FAILURE|ERROR|ERR!|FATAL)(?=[\s:(\[]|$)"),
    re.compile(r"^(?:E\s+)?(?:[A-Za-z_][\w$]*[.:])*(?:[A-Z]\w*)?(?:Error|Exception|Exit|Interrupt|Fault)\b(?![\w.])"),
    re.compile(r"^(?:panic|fatal|error)(?:\[\w+\])?:|^##\[error\]|(?::\d+(?::\d+)?:|\(\d+,\d+\):)\s*(?:fatal )?error\b", re.I),
    re.compile(r"\bexit(?:ed)?(?: with)?(?: code| status)?\s+[1-9]\d*\b|\bError [1-9]\d*\s*$", re.I),
)


@dataclass(frozen=True)
class Root:
    path: Path
    #: A directory name the file must sit beneath inside the root, or "" for anywhere in it.
    under: str = ""


@dataclass(frozen=True)
class File:
    path: str
    size: int
    text: str


def claude_roots() -> list[Root]:
    """Claude Code's offloaded tool output and background task output."""
    base = Path(os.environ.get(CLAUDE_ENV) or Path.home() / ".claude")
    out = [Root(base / "projects", "tool-results")]
    uid = getattr(os, "getuid", None)
    if uid is not None:
        out.append(Root(Path("/tmp") / f"claude-{uid()}", "tasks"))
    return out


def configured() -> list[Root]:
    raw = os.environ.get(ROOTS_ENV) or ""
    return [Root(Path(p).expanduser()) for p in raw.split(os.pathsep) if p.strip()]


def worktree(cwd: Path) -> Path:
    """The git worktree holding `cwd`, else `cwd` itself."""
    here = Path(os.path.realpath(cwd))
    for d in (here, *here.parents):
        if (d / ".git").exists():
            return d
    return here


def default_roots(cwd: Path | None = None) -> list[Root]:
    from harness import paths
    out = [*claude_roots(), Root(paths.logs()), *configured()]
    if cwd is not None:
        out.append(Root(worktree(cwd)))
    return out


def _under(path: Path, base: Path, under: str) -> bool:
    try:
        rel = path.relative_to(base)
    except ValueError:
        return False
    return not under or under in rel.parts[:-1]


def _inside(real: Path, root: Root) -> bool:
    return _under(real, Path(os.path.realpath(root.path)), root.under)


def _named(lexical: Path, root: Root) -> bool:
    bases = {Path(os.path.abspath(root.path)), Path(os.path.realpath(root.path))}
    return any(_under(lexical, b, root.under) for b in bases)


def check(raw, roots: list[Root], cwd: Path | None = None) -> Path:
    """The real path of `raw` when it resolves inside a root; Refused otherwise."""
    text = str(raw or "")
    if not text.strip():
        raise Refused("an empty path")
    if "\0" in text:
        raise Refused("a path with a NUL byte")
    p = Path(text).expanduser()
    if not p.is_absolute():
        if cwd is None:
            raise Refused(f"{text}: give an absolute path; the server's working directory is not yours")
        p = Path(cwd) / p
    real = Path(os.path.realpath(p))
    if any(_inside(real, r) for r in roots):
        return real
    names = ", ".join(f"{r.path}" + (f" (under {r.under}/)" if r.under else "") for r in roots)
    if any(_named(Path(os.path.abspath(p)), r) for r in roots):
        raise Refused(f"{text} is a symlink out of the roots this reads: {names}")
    raise Refused(f"{text} is outside the roots this reads: {names}. Set {ROOTS_ENV} to add one")


def _regular(st: os.stat_result, raw: str) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise Refused(f"{raw} is not a regular file")
    # A hard link inside a root can name a file outside it, and realpath cannot see that.
    if st.st_nlink > 1:
        raise Refused(f"{raw} has {st.st_nlink} hard links; copy it before asking")


def _open(real: Path, raw: str, seen: os.stat_result) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(real, flags)
    except OSError as exc:
        raise Refused(f"{raw}: {exc.strerror or exc}") from exc
    st = os.fstat(fd)
    if (st.st_dev, st.st_ino) != (seen.st_dev, seen.st_ino):
        os.close(fd)
        raise Refused(f"{raw} changed while it was checked")
    return fd


def read(raws, roots: list[Root], cwd: Path | None = None, max_bytes: int = MAX_BYTES) -> list[File]:
    """Each path's text, after every path passed the roots, the file-type and the byte-cap checks."""
    raws = [raws] if isinstance(raws, (str, Path)) else list(raws or [])
    if not raws:
        raise Refused("no paths")
    if len(raws) > MAX_PATHS:
        cuts.cut("harness/ask.py:MAX_PATHS", f"a {len(raws)}-path digest refused", kept=0, dropped=len(raws))
        raise Refused(f"{len(raws)} paths, over the {MAX_PATHS}-path cap")
    reals = [check(r, roots, cwd) for r in raws]
    stats = []
    for raw, real in zip(raws, reals):
        try:
            stats.append(os.stat(real))
        except OSError as exc:
            raise Refused(f"{raw}: {exc.strerror or exc}") from exc
        _regular(stats[-1], str(raw))
    total = sum(st.st_size for st in stats)
    if total > max_bytes:
        cuts.cut("harness/ask.py:MAX_BYTES", f"a {total}-byte digest refused", value=max_bytes, kept=0, dropped=total)
        raise Refused(f"{total} bytes in {len(raws)} file(s), over the {max_bytes}-byte cap; "
                      f"grep or tail it to a smaller file first")
    out, left = [], max_bytes
    for raw, real, seen in zip(raws, reals, stats):
        with os.fdopen(_open(real, str(raw), seen), "rb") as fh:
            data = fh.read(left + 1)
        if len(data) > left:
            raise Refused(f"{raw} grew past the {max_bytes}-byte cap while it was read")
        if b"\0" in data:
            raise Refused(f"{raw} looks binary (it holds NUL bytes)")
        left -= len(data)
        out.append(File(str(real), len(data), data.decode("utf-8", "replace")))
    return out


def _pieces(text: str, size: int):
    for line in text.splitlines(keepends=True) or [""]:
        while len(line) > size:
            yield line[:size]
            line = line[size:]
        yield line


def chunks(files: list[File], size: int = CHUNK_CHARS) -> list[str]:
    """Each file cut on line boundaries into parts of at most `size` characters, each headed by name and lines."""
    out = []
    for f in files:
        name = Path(f.path).name
        buf, n, start, line = [], 0, 1, 0
        for line, piece in enumerate(_pieces(f.text, size), 1):
            if buf and n + len(piece) > size:
                out.append(f"=== {name}, lines {start}-{line - 1} ===\n" + "".join(buf))
                buf, n, start = [], 0, line
            buf.append(piece)
            n += len(piece)
        out.append(f"=== {name}, lines {start}-{max(start, line)} ===\n" + "".join(buf))
    return out


def is_none(answer: str) -> bool:
    t = (answer or "").strip().strip("`'\"*.:! ").lower()
    return not t or t in _NONE_WORDS or (t.startswith("none") and len(t) <= 24)


def clean(answer: str) -> str:
    """The answer, or NONE; a stray none line beside real lines is dropped."""
    lines = [ln for ln in (answer or "").strip().splitlines() if ln.strip()]
    kept = [ln for ln in lines if not is_none(ln)]
    return "\n".join(kept).strip() if kept else NONE


def _flat(text: str) -> str:
    return " ".join(text.split())


def ground(answer: str, text: str, question: str) -> str:
    """The answer's lines that quote `text`: a line with words no line of the files holds was made up, and
    for a question about failures a quote of only lines that did not fail (PASSED, XFAIL...) is dropped."""
    if is_none(answer):
        return NONE
    source = [_flat(ln) for ln in text.splitlines() if ln.strip()]
    failing = bool(_ABOUT_FAILURE.search(question or ""))
    kept = []
    for line in clean(answer).splitlines():
        bare = _flat(line.strip().lstrip("-*\u2022 ").strip().strip("`\"'"))
        if not re.search(r"[A-Za-z]", bare):
            if not failing:
                kept.append(line)
            continue
        if failing and _CALM_COUNT.search(bare) and not _FAILING_WORD.search(bare):
            continue
        holding = [ln for ln in source if bare in ln]
        if not holding or (failing and all(_NOT_FAILING.search(ln) for ln in holding)):
            continue
        kept.append(line)
    return "\n".join(kept) if kept else NONE


def _clip(line: str, at: int) -> str:
    if len(line) <= LINE_CHARS:
        return line
    start = max(0, min(at - LINE_CHARS // 3, len(line) - LINE_CHARS))
    return line[start:start + LINE_CHARS]


def failure_lines(text: str) -> list[str]:
    """Each distinct line of `text` shaped like a failure (nonzero count, FAILED/ERROR, exception, error mark, nonzero exit)."""
    out, seen, clipped = [], set(), 0
    for raw in text.splitlines():
        line = _STAMP.sub("", raw).strip()
        if not line or _NOT_FAILING.search(line):
            continue
        hit = next((m for m in (p.search(line) for p in _FAILURE) if m), None)
        if hit is None:
            continue
        clipped += len(line) > LINE_CHARS
        line = _clip(line, hit.start())
        if line not in seen:
            seen.add(line)
            out.append(line)
    if clipped:
        cuts.cut("harness/ask.py:LINE_CHARS", f"{clipped} failure line(s) clipped", value=LINE_CHARS,
                 kept=len(out), dropped=clipped)
    return out


def with_failures(answer: str, text: str) -> tuple[str, int]:
    """The answer with the scan's failure lines it does not already quote, a quoted fragment widened to its line;
    (answer, lines added)."""
    kept = [] if is_none(answer) else answer.splitlines()
    have = [_flat(ln.strip().lstrip("-*• ").strip("`\"'")) for ln in kept]
    widened, found = set(), []
    for ln in failure_lines(text):
        flat = _flat(ln)
        if any(flat in h for h in have):
            continue
        at = next((i for i, h in enumerate(have) if i not in widened and re.search(r"[A-Za-z]", h) and h in flat), None)
        if at is None:
            found.append(ln)
        else:
            widened.add(at)
            kept[at] = ln
    if len(found) > FAILURE_LINES:
        cuts.cut("harness/ask.py:FAILURE_LINES", "a digest's failure scan kept its first lines", value=FAILURE_LINES,
                 kept=FAILURE_LINES, dropped=len(found) - FAILURE_LINES)
        found = found[:FAILURE_LINES]
    lines = kept + found
    return ("\n".join(lines) if lines else NONE), len(found)


def _ask_one(question: str, part: str) -> str:
    return f"Question: {question.strip()}\n\n{part}"


def _merge(question: str, notes: list[str]) -> str:
    body = "\n\n".join(f"--- note {i} ---\n{n}" for i, n in enumerate(notes, 1))
    return f"{MERGE}\n\nQuestion: {question.strip()}\n\n{body}"


def _pack(notes: list[str], size: int) -> list[list[str]]:
    groups, cur, n = [], [], 0
    for note in notes:
        if len(cur) >= 2 and n + len(note) > size:
            groups.append(cur)
            cur, n = [], 0
        cur.append(note)
        n += len(note)
    if len(cur) == 1 and groups:
        groups[-1].append(cur.pop())
    return groups + ([cur] if cur else [])


def digest(files: list[File], question: str, call, size: int = CHUNK_CHARS) -> tuple[str, int, int]:
    """(answer, parts, calls): one call per part, then merges of the parts that answered until one is left."""
    parts = chunks(files, size)
    if len(parts) > 1:
        cuts.cut("harness/ask.py:CHUNK_CHARS", f"a digest asked in {len(parts)} parts", value=size,
                 kept=len(parts), dropped=0)
    text = "\n".join(f.text for f in files)
    notes = [a for a in (ground(call(_ask_one(question, p)), text, question) for p in parts) if a != NONE]
    calls = len(parts)
    while len(notes) > 1:
        groups = _pack(notes, size)
        notes = [a for a in (ground(call(_merge(question, g)), text, question) for g in groups) if a != NONE]
        calls += len(groups)
    return (notes[0] if notes else NONE), len(parts), calls


def chunk_chars(lane: str, max_tokens: int) -> int:
    """CHUNK_CHARS, smaller when the lane's served context leaves less beside the reply and the prompts."""
    from harness import context, methods
    try:
        spec, _ = delegate.route(lane)
        ctx = context.served_ctx(methods.base_of(spec) or spec)
    except Exception:  # noqa: BLE001
        ctx = None
    if not ctx:
        return CHUNK_CHARS
    room = (ctx - int(max_tokens) - 1024) * delegate.CHARS_PER_TOKEN
    return max(2000, min(CHUNK_CHARS, room))


def _total(replies: list[dict], key: str):
    counts = [r.get(key) for r in replies]
    return sum(counts) if counts and all(c is not None for c in counts) else None


def ask(raws, question: str, lane: str = "extract", roots: list[Root] | None = None,
        cwd: Path | None = None, max_tokens: int | None = None, system: str | None = None,
        thinking: bool | None = None, delegated: bool = False, complete=None,
        size: int | None = None) -> dict:
    """The answer to `question` about the files, with the paths and byte counts it read; never their text."""
    lane = delegate.check_lane(lane)
    max_tokens = int(max_tokens or REPLY_TOKENS)
    if not (question or "").strip():
        raise Refused("empty question")
    files = read(raws, default_roots(cwd) if roots is None else roots, cwd)
    complete = complete or delegate.complete
    if thinking is None and lane == "code":
        thinking = False
    replies: list[dict] = []

    def call(prompt: str) -> str:
        got = complete(lane, prompt, system=system or SYSTEM, max_tokens=max_tokens, thinking=thinking,
                       tag=purpose.WORK if delegated else purpose.INTERNAL)
        replies.append(got)
        if (got.get("completion_tokens") or 0) >= max_tokens:
            cuts.cut("harness/ask.py:REPLY_TOKENS", "a digest reply reached its token budget", value=max_tokens,
                     kept=1, dropped=0)
        return got["text"]
    started = time.perf_counter()
    text, parts, calls = digest(files, question, call, size or chunk_chars(lane, max_tokens))
    scanned = 0
    if _ABOUT_FAILURE.search(question):
        text, scanned = with_failures(text, "\n".join(f.text for f in files))
    last = replies[-1]
    out = {"text": text, "lane": lane, "spec": last.get("spec", ""), "model": last.get("model", ""),
           "ttft_s": replies[0].get("ttft_s"), "seconds": round(time.perf_counter() - started, 4),
           "prompt_tokens": _total(replies, "prompt_tokens"),
           "completion_tokens": _total(replies, "completion_tokens"), "method": None, "call_id": "",
           "files": [{"path": f.path, "bytes": f.size} for f in files], "parts": parts, "calls": calls,
           "scanned": scanned}
    if delegated:
        from harness import delegations
        out = delegations.note(out, delegations.new_id())
    return out


def local_client(request) -> bool:
    """True when an MCP request came from this machine: no HTTP request (stdio), loopback, or the server's own address."""
    if request is None:
        return True
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if not host:
        return False
    server = ((getattr(request, "scope", None) or {}).get("server") or ("",))[0]
    if server and host == server:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    return addr.is_loopback or bool(mapped and mapped.is_loopback)


def _tool_uses(path: Path):
    from harness.context_report import _epoch
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if '"tool_use"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            content = (d.get("message") or {}).get("content") if isinstance(d, dict) else None
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    given = c.get("input") if isinstance(c.get("input"), dict) else {}
                    yield str(c.get("name") or ""), given, _epoch(d.get("timestamp"))


def _norm(p) -> str:
    return os.path.normpath(str(p))


def redos(files, window: int = REDO_WINDOW, since: float | None = None) -> dict:
    """Digests by path made at or after `since`, and how many a full Read of the same path followed within `window` tool calls."""
    digests = redone = 0
    examples = []
    for path in files:
        uses = list(_tool_uses(Path(path)))
        for i, (name, given, at) in enumerate(uses):
            if not name.endswith("local_complete") or not given.get("paths"):
                continue
            if since is not None and (at is None or at < since):
                continue
            wanted = {_norm(p) for p in (given["paths"] if isinstance(given["paths"], list) else [given["paths"]])}
            digests += 1
            for later, again, _ in uses[i + 1:i + 1 + window]:
                if (later == "Read" and _norm(again.get("file_path", "")) in wanted
                        and again.get("offset") is None and again.get("limit") is None):
                    redone += 1
                    examples.append({"transcript": str(path), "path": _norm(again["file_path"])})
                    break
    return {"digests": digests, "redos": redone,
            "rate": (redone / digests) if digests else None, "examples": examples[:10]}
