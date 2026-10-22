"""Redact a person's own words before they become a committed case: each finding becomes a stable typed placeholder. #1095."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

#: Placeholder classes in the order they apply; earlier classes win an overlap.
CLASSES = ("paste", "session", "request", "id", "secret", "email", "path", "host", "ip", "chat", "handle",
           "account", "name")
_SECRETS = [re.compile(p, re.S) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
    r"\bsk-ant-[A-Za-z0-9_-]{16,}",
    r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{16,}",
    r"\bgh[opusr]_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    r"\bxox[abposr]-[A-Za-z0-9-]{10,}",
    r"\bAIza[0-9A-Za-z_-]{30,}",
    r"\bhf_[A-Za-z0-9]{20,}",
    r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}",
    r"\bsbp_[A-Za-z0-9]{20,}",
    r"\bnpm_[A-Za-z0-9]{20,}",
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    r"(?i)(?<=bearer )[A-Za-z0-9._~+/=-]{16,}",
    r"(?i)(?<=://)[^\s:/@]+:[^\s:/@]+(?=@)",
)]
#: A value assigned to a key-like name; group 1 is the value alone.
_ASSIGNED = re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|auth)\b[\"']?\s*[:=]\s*[\"']?([^\s\"']{8,})")
#: Text the person pasted rather than wrote, as Claude Code marks it: another chat, a log, someone else's words.
_PASTE = re.compile(r"<pasted_content\b[^>]*>.*?(?:</pasted_content[^>]*>|\Z)", re.S)
_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
_RUN = re.compile(r"[A-Za-z0-9+]+")
_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_PATTERNS = {
    "session": [re.compile(r"\bsession_[A-Za-z0-9]{16,}\b")],
    "request": [re.compile(r"\breq_[A-Za-z0-9]{16,}\b")],
    "id": [re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
           re.compile(r"\b(?:msg|toolu|srvtoolu|file|batch|agent)_[A-Za-z0-9]{12,}\b"),
           re.compile(r"\bagent-a[0-9a-f]{15,17}\b"),
           re.compile(r"(?<![\d.])\d{17,20}(?![\d.])")],
    "email": [re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")],
    "host": [re.compile(r"(?<![\w<.-])(?!cluster\.local\b)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
                        r"\.(?:local|lan|home\.arpa|internal|localdomain)\b")],
    "ip": [re.compile(r"(?<![\w.])(?!127\.)(?!0\.0\.0\.0)(?:25[0-5]|2[0-4]\d|1?\d?\d)"
                      r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])"),
           re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}(?![\w:])"),
           re.compile(r"(?<![\w:])(?=[0-9a-fA-F:]*::)(?=[0-9a-fA-F:]*[0-9a-fA-F]{3})[0-9a-fA-F]{0,4}"
                      r"(?::[0-9a-fA-F]{0,4}){2,7}(?![\w:])"),
           re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")],
    "handle": [re.compile(r"<@[!&]?\d{5,}>"), re.compile(r"\b(?:member|user)-(?=[0-9a-f]*\d)[0-9a-f]{4,}\b"),
               re.compile(r"\bmember-[A-Z]{1,2}\b")],
}
_HOME = re.compile(r"(?:/(?:Users|home)/|[A-Za-z]:\\Users\\)(?!USER\b|you\b|user\b|<)[^/\\\s'\"`]+(?=[/\\]|\s|$|['\"`])")
_VOLUME = re.compile(r"(?<!System)/Volumes/[^/\s'\"`]+")
_TMP = re.compile(r"/(?:private/)?var/folders/[^\s'\"`]+")
_CHAT = [re.compile(p) for p in (
    r"^\s*\[\d+\]\s*[^:\n\[\]]{1,64}:\s",
    r"^\s*\[?\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp]\.?[Mm]\.?)?\]?\s*[-–—]?\s*[^:\n]{1,40}:\s",
    r"^.{1,40}\s[—–-]\s(?:Today|Yesterday|\d{1,2}/\d{1,2}/\d{2,4})(?:\s+at)?\s+\d{1,2}:\d{2}",
)]
_HEADER = _CHAT[2]
_PLACEHOLDER = re.compile(r"<(?:[A-Z]+_\d+|PATH_HOME|PATH_TMP)>")


@dataclass(frozen=True)
class Known:
    """What one machine knows is private but no pattern can: account names, people's names, host names."""
    accounts: tuple = ()
    names: tuple = ()
    hosts: tuple = ()


@dataclass
class Redacted:
    text: str
    counts: dict = field(default_factory=dict)


def entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values()) if n else 0.0


def _random_run(run: str) -> bool:
    """A run of letters and digits as a key generator makes one: long, all three classes, few repeats."""
    wordy = sum(len(w) for w in re.findall(r"[A-Z]?[a-z]{3,}", run))
    return (len(run) >= 16 and any(c.isupper() for c in run) and any(c.islower() for c in run)
            and sum(c.isdigit() for c in run) >= 2 and entropy(run) >= 3.5 and wordy < len(run) / 2)


def high_entropy(text: str):
    """Spans of tokens that look random: a mixed-case alphanumeric run, or hex too long for a commit sha."""
    for m in _TOKEN.finditer(text):
        for r in _RUN.finditer(m.group(0)):
            if _random_run(r.group(0)):
                yield m.start() + r.start(), m.start() + r.end()
    for m in _HEX.finditer(text):
        if len(m.group(0)) != 40 and len(set(m.group(0).lower())) >= 8:
            yield m.span()


#: Names every machine spells the same way; documentation address blocks (RFC 5737) name nobody.
_GENERIC_HOSTS = re.compile(r"(?:^|\.)(?:cluster\.local|host\.docker\.internal)$", re.I)
_DOC_IP = re.compile(r"^(?:192\.0\.2|198\.51\.100|203\.0\.113)\.")


def _generic(cls: str, value: str) -> bool:
    return (cls == "host" and bool(_GENERIC_HOSTS.search(value))) or (cls == "ip" and bool(_DOC_IP.match(value)))


def _words(values) -> re.Pattern | None:
    vals = sorted({v.strip() for v in values if v and len(v.strip()) >= 2}, key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(v) for v in vals) + r")(?![\w-])", re.I) if vals else None


def _chat_lines(text: str):
    """Spans of pasted chat: speaker-tagged lines, and a chat header with the lines under it up to a blank."""
    pos, inside = 0, False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if _HEADER.match(body):
            inside = True
        hit = inside or any(p.match(body) for p in _CHAT)
        if not body.strip():
            inside = False
        if hit and body.strip():
            yield pos, pos + len(body)
        pos += len(line)


def _spans(text: str, known: Known):
    """(start, end, class, value) of every finding, earliest class first."""
    out = [(m.start(), m.end(), "paste") for m in _PASTE.finditer(text)]
    for p in _SECRETS:
        out += [(m.start(), m.end(), "secret") for m in p.finditer(text)]
    out += [(m.start(1), m.end(1), "secret") for m in _ASSIGNED.finditer(text)]
    out += [(a, b, "secret") for a, b in high_entropy(text)]
    for cls in ("session", "request", "id", "email"):
        out += [(m.start(), m.end(), cls) for p in _PATTERNS[cls] for m in p.finditer(text)]
    out += [(m.start(), m.end(), "path") for p in (_HOME, _VOLUME, _TMP) for m in p.finditer(text)]
    for cls, extra in (("host", known.hosts), ("ip", ()), ("handle", ())):
        pats = list(_PATTERNS[cls]) + ([w] if (w := _words(extra)) else [])
        out += [(m.start(), m.end(), cls) for p in pats for m in p.finditer(text) if not _generic(cls, m.group(0))]
    out += [(a, b, "chat") for a, b in _chat_lines(text)]
    for cls, extra in (("account", known.accounts), ("name", known.names)):
        if (w := _words(extra)):
            out += [(m.start(), m.end(), cls) for m in w.finditer(text)]
    rank = {c: i for i, c in enumerate(CLASSES)}
    out.sort(key=lambda s: (s[0], rank[s[2]], -s[1]))
    kept, end = [], -1
    for a, b, cls in out:
        if a >= end and not _PLACEHOLDER.fullmatch(text[a:b]):
            kept.append((a, b, cls, text[a:b]))
            end = b
    return kept


def _placeholder(cls: str, value: str, seen: dict) -> str:
    if cls == "path":
        if _HOME.match(value):
            return "<PATH_HOME>"
        if _TMP.match(value):
            return "<PATH_TMP>"
        cls = "volume"
    key = (cls, value.lower() if cls in ("email", "host", "account", "name") else value)
    if key not in seen:
        seen[key] = sum(1 for k in seen if k[0] == cls) + 1
    return f"<{cls.upper()}_{seen[key]}>"


def redact(text: str, known: Known = Known()) -> Redacted:
    """`text` with every finding replaced by a typed placeholder that is stable per value, and the count per class."""
    seen, counts, out, pos = {}, Counter(), [], 0
    for a, b, cls, value in _spans(text, known):
        out += [text[pos:a], _placeholder(cls, value, seen)]
        counts[cls] += 1
        pos = b
    out.append(text[pos:])
    return Redacted("".join(out), dict(sorted(counts.items())))


def detect(text: str, known: Known = Known()) -> dict:
    """class -> findings still in `text`; empty means nothing left to redact."""
    return dict(sorted(Counter(cls for *_, cls, _ in _spans(text, known)).items()))


def known_here(name_files=()) -> Known:
    """This machine's account, git identity, host name, the privacy lint's private names (here and in the main
    checkout, which a worktree lacks) and one name per line from each of `name_files`."""
    import getpass
    import socket
    import subprocess
    from pathlib import Path

    from harness import privacy
    root = Path(__file__).resolve().parent.parent
    accounts = {getpass.getuser(), Path.home().name}
    common = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    names = set(privacy.names(root)) | (set(privacy.names(Path(common).parent)) if common else set())
    for f in name_files:
        names |= {n.strip() for n in Path(f).read_text(encoding="utf-8").splitlines() if n.strip()}
    got = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True)
    names |= {w for w in got.stdout.split() if len(w) >= 3}
    host = socket.gethostname().split(".")[0]
    return Known(accounts=tuple(sorted(accounts)), names=tuple(sorted(names)),
                 hosts=tuple(sorted({host} if host and host != "localhost" else set())))
