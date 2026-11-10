"""A log or test output digested by a local model, checked for every failing test and error line, with a pointer to the raw file. #1690."""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from pathlib import Path

from harness import ask, completion, cuts, delegate

QUESTION = ("Which tests failed, and which errors, failure counts and nonzero exits does this log show? "
            "Name each failing test and quote each error line exactly as the log writes it.")
#: Characters per token of what Claude reads, the measure FINDING #867 counted carried context in.
TOKEN_CHARS = 4
#: Lines the check adds to one digest before it names the rest by count.
CHECK_ITEMS = 60
#: Characters of an exception line that must reappear in the digest.
KEY_CHARS = 80
CONTROL = "test_digest_check_control"
_CONTROL_BLOCK = (f"{'_' * 10} {CONTROL} {'_' * 10}\nE   AssertionError: digest check control\n"
                  f"tests/{CONTROL}.py:1: AssertionError\n")

_HEAD = re.compile(r"^_{3,} (\S.*?) _{3,}$")
_SECTION = re.compile(r"^={3,}")
_E = re.compile(r"^E\s{2,}(\S.*)$")
_LOC = re.compile(r"^(\S+\.py):(\d+): (\w[\w.]*)$")
_SUMMARY = re.compile(r"^(?:FAILED|ERROR) (\S+?\.py(?:::\S+)?)(?: - .*)?$")
_COUNT = re.compile(r"\b([1-9]\d*) (failed|errors?)\b")
_COUNT_LINE = re.compile(r"^=*\s*(?:\d+ \w+(?:, )?)+ in [\d.]+s\b")
_EXIT = re.compile(r"^(?:make(?:\[\d+\])?: \*\*\* .*\bError [1-9]\d*|##\[error\].*"
                   r"|(?!E\s).*\bexit(?:ed)? (?:with )?(?:code|status) [1-9]\d*\.?)$")


@dataclass(frozen=True)
class Item:
    #: test, exception, count or exit.
    kind: str
    #: What must appear in a digest that kept this item.
    key: str
    #: What the check adds when the digest left it out.
    line: str


def tokens(text: str) -> int:
    return -(-len(text or "") // TOKEN_CHARS)


def short(name: str) -> str:
    """A test's own name: `tests/x.py::C::test_y[p]` and `C.test_y[p]` are both `test_y[p]`."""
    name = name.strip()
    for word in ("ERROR at setup of ", "ERROR at teardown of ", "ERROR at call of "):
        if name.startswith(word):
            name = name[len(word):]
    base, bracket, param = name.partition("[")
    if "::" in base:
        base = base.rsplit("::", 1)[-1]
    elif not base.endswith(".py"):
        base = base.rsplit(".", 1)[-1]
    return base + bracket + param


def must(text: str) -> list[Item]:
    """What a digest of `text` has to keep: each failing test, its first exception line, failure counts, nonzero exits."""
    out: dict[tuple[str, str], Item] = {}

    def add(kind: str, key: str, line: str) -> None:
        out.setdefault((kind, key), Item(kind, key, line))

    name, loc, exc = "", "", ""
    keyed = []

    def close() -> None:
        if name:
            add("test", short(name), f"FAILED {name}" + (f" ({loc})" if loc else ""))
            if exc:
                flat = " ".join(exc.split())
                keyed.append(len(flat) > KEY_CHARS)
                add("exception", flat[:KEY_CHARS], f"E   {flat[:ask.LINE_CHARS]}")
    for raw in ask.plain(text).splitlines():
        line = raw.rstrip()
        head = _HEAD.match(line)
        if head or _SECTION.match(line):
            close()
            name, loc, exc = "", "", ""
            if head and not head.group(1).startswith(("Captured", "warnings summary")):
                name = head.group(1)
                if name.startswith("ERROR collecting "):
                    add("test", name[len("ERROR collecting "):], name)
                    name = ""
        if name:
            e, at = _E.match(line), _LOC.match(line)
            if e and not exc:
                exc = e.group(1)
            if at:
                loc = line
        hit = _SUMMARY.match(line)
        if hit:
            add("test", short(hit.group(1)), line)
        if _COUNT_LINE.match(line.strip()):
            for n, word in _COUNT.findall(line):
                add("count", f"{n} {word}", line.strip("= "))
        if _EXIT.match(line.strip()):
            add("exit", " ".join(line.split()), line.strip())
    close()
    if any(keyed):
        cuts.cut("harness/digest.py:KEY_CHARS", "exception lines checked by their first characters", value=KEY_CHARS,
                 kept=len(keyed) - sum(keyed), dropped=sum(keyed))
    return list(out.values())


def _present(item: Item, flat: str) -> bool:
    if item.kind != "test":
        return item.key in flat
    return re.search(r"(?<![\w-])" + re.escape(item.key) + r"(?![\w\[-])", flat) is not None


def missing(digest_text: str, items: list[Item]) -> list[Item]:
    """The items a digest left out; a test counts as kept when its own name appears in it as a whole word."""
    flat = " ".join((digest_text or "").split())
    return [i for i in items if not _present(i, flat)]


def control(text: str, digest_text: str) -> bool:
    """True when the check, given `text` with one failing test planted, finds the plant missing from the digest."""
    planted = must(text + "\n" + _CONTROL_BLOCK)
    return any(i.kind == "test" and i.key == CONTROL for i in missing(digest_text, planted))


def pointer(f: ask.File) -> str:
    return (f"raw: {f.path} ({f.text.count(chr(10)) + 1} lines, {f.size} bytes, about {tokens(f.text)} tokens "
            f"to Read whole; Read with offset/limit for more)")


def _scan_only(files: list[ask.File], lane: str, why: str) -> dict:
    text, scanned = ask.with_failures(ask.NONE, "\n".join(f.text for f in files))
    return {"text": text, "model_text": "", "lane": lane, "spec": "", "model": "", "ttft_s": None, "seconds": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0, "method": None, "call_id": "", "parts": 0, "calls": 0,
            "scanned": scanned, "unmodelled": why}


def run(raws, question: str = "", lane: str = "extract", roots: list[ask.Root] | None = None, cwd: Path | None = None,
        max_tokens: int | None = None, delegated: bool = True, complete=None, size: int | None = None,
        model: bool = True) -> dict:
    """The digest of the files: the model's answer and the failure scan, every item the check found it left out,
    the control's verdict and a pointer to each raw file. With no model (or a refusal) the scan stands alone."""
    files = ask.read(raws, ask.default_roots(cwd) if roots is None else roots, cwd)
    plain = [ask.File(f.path, f.size, ask.plain(f.text)) for f in files]
    got = None
    if model:
        try:
            got = ask.ask(None, question or QUESTION, lane=lane, files=plain, max_tokens=max_tokens,
                          delegated=delegated, complete=complete, size=size)
        except (delegate.Refused, completion.CompletionError) as exc:
            got = _scan_only(plain, lane, f"the {lane} lane did not answer: {exc}")
    got = got or _scan_only(plain, lane, "asked for no model")
    joined = "\n".join(f.text for f in plain)
    items = must(joined)
    left = missing(got["text"], items)
    if len(left) > CHECK_ITEMS:
        cuts.cut("harness/digest.py:CHECK_ITEMS", "a digest check named its first missing lines", value=CHECK_ITEMS,
                 kept=CHECK_ITEMS, dropped=len(left) - CHECK_ITEMS)
    body = [] if ask.is_none(got["text"]) and left else [got["text"]]
    if left:
        body.append("check added (the digest left these out):")
        body.extend(i.line for i in left[:CHECK_ITEMS])
        if len(left) > CHECK_ITEMS:
            body.append(f"... and {len(left) - CHECK_ITEMS} more; read the raw file")
    caught = control(joined, "\n".join(body))
    kinds = collections.Counter(i.kind for i in items)
    summary = (f"check: {len(items)} item(s) ({', '.join(f'{v} {k}' for k, v in sorted(kinds.items())) or 'none'}), "
               f"digest kept {len(items) - len(left)}, check added {min(len(left), CHECK_ITEMS)}; "
               + ("control caught" if caught else "CONTROL MISSED a planted failure: read the raw file"))
    tail = [summary, *(pointer(f) for f in files)]
    if got.get("unmodelled"):
        tail.insert(0, f"no model: {got['unmodelled']}; this is the failure scan alone")
    text = "\n".join(body + tail)
    return {**got, "answer": got["text"], "text": text,
            "files": [{"path": f.path, "bytes": f.size} for f in files],
            "check": {"items": len(items), "kinds": dict(kinds), "kept": len(items) - len(left),
                      "added": min(len(left), CHECK_ITEMS), "missing": [i.key for i in left], "control": caught},
            "raw_tokens": sum(tokens(f.text) for f in files), "digest_tokens": tokens(text)}
