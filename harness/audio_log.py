"""A tts request's own traceback, cut from the audio server's log when the server drops the stream. #1036."""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

#: The excerpt's name in a run directory.
FILE = "server-error.log"
#: uvicorn's line before the traceback of an app that raised after the response started.
_ASGI = "Exception in ASGI application"
_CHAIN = ("Traceback (most recent call last):", "The above exception", "During handling of the above exception")
_EXCEPTION = re.compile(r"^(?:(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*(?:Error|Exception|Exit|Interrupt|Timeout|Fault|Group)"
                        r"|(?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*)(?:: .*)?$")


def _bare(line: str) -> str:
    """A traceback line without the bars an exception group indents it with."""
    s = line.rstrip("\r\n")
    return s.lstrip(" |+") if s.lstrip().startswith(("|", "+")) else s


class Excerpt(NamedTuple):
    log: str
    first: int
    last: int
    lines: list

    @property
    def errors(self) -> list[str]:
        """The exception lines of the traceback chain, outermost first, each once."""
        seen = []
        for line in reversed(self.lines):
            s = _bare(line)
            if _EXCEPTION.match(s) and s not in seen:
                seen.append(s)
        return seen


def logs() -> list[Path]:
    """Where the audio server's output lands: launchd's tts service, else services.sh's audio files."""
    import os

    from harness import load_log, paths
    serving = os.environ.get(load_log.SERVING_ENV)
    d = Path(serving).expanduser() / "logs" if serving else paths.logs()
    return [d / "tts.log", d / "audio.err.log", d / "audio.log"]


def mark(base_url: str) -> dict[str, int]:
    """Each local audio log's size before a request; {} when the server is another machine's."""
    from harness import machine
    if not machine.is_loopback(base_url):
        return {}
    return {str(p): p.stat().st_size if p.is_file() else 0 for p in logs()}


def _block(lines, i: int) -> int | None:
    """The index of the last exception line of the traceback after lines[i], or None."""
    end = None
    for j in range(i + 1, len(lines)):
        s = lines[j].rstrip("\r\n")
        if _EXCEPTION.match(_bare(s)):
            end = j
        elif s.strip() and not s[:1].isspace() and not s.startswith(_CHAIN):
            break
    return end


def cut(lines, log: str = "", base: int = 0) -> Excerpt | None:
    """The first traceback uvicorn logged for an app that raised mid-response; `base` is the line before lines[0]."""
    lines = list(lines)
    for i, line in enumerate(lines):
        if _ASGI in line:
            end = _block(lines, i)
            if end is not None:
                return Excerpt(log, base + i + 1, base + end + 1, lines[i:end + 1])
    return None


def since(marks: dict[str, int]) -> Excerpt | None:
    """The first excerpt in what each marked log gained after its mark; a log that shrank was rotated and is read whole."""
    for path, at in marks.items():
        p = Path(path)
        if not p.is_file():
            continue
        if p.stat().st_size < at:
            at = 0
        with open(p, "rb") as fh:
            before = fh.read(at).count(b"\n")
            text = fh.read().decode("utf-8", errors="replace")
        got = cut(text.splitlines(keepends=True), str(p), before)
        if got:
            return got
    return None


def source(ex: Excerpt) -> str:
    return f"{Path(ex.log).name} lines {ex.first}-{ex.last}"


def write(outdir: Path, ex: Excerpt) -> Path:
    path = Path(outdir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {source(ex)}\n" + "".join(
        line if line.endswith("\n") else line + "\n" for line in ex.lines), encoding="utf-8")
    return path
