"""`soh claude-news`: Claude Code changelog entries newer than the last version seen, split by relevance to this setup. #866."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
FETCH_TIMEOUT_S = 30.0
VERSION_TIMEOUT_S = 15.0
LAST_KEY = "claude_news:last_version"
NOTIFY_TITLE = "SoHoT claude-news"

_HEADING = re.compile(r"^#{2,3}\s+\[?v?(\d+(?:\.\d+)+)\]?")
_ITEM = re.compile(r"^\s*[-*]\s+(.*\S)")
_SEMVER = re.compile(r"(\d+\.\d+\.\d+)")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")

QUESTION = ("Here is one entry from the Claude Code changelog. The context describes how this "
            "machine runs Claude Code: its settings keys, the hook events it uses, its enabled "
            "plugins and its installed version. Is the entry relevant to how this machine runs: "
            "does it change, fix or add something this setup uses or could directly use?\n\nEntry: ")
SCHEMA = {"relevant": {"type": "boolean",
                       "description": "true when the entry bears on this setup, false otherwise"}}


@dataclass(frozen=True)
class Entry:
    version: str
    text: str

    def as_dict(self) -> dict:
        return {"version": self.version, "text": self.text}


def vkey(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def parse(text: str) -> list[Entry]:
    """Every bulleted entry under a version heading, in file order."""
    out, version = [], None
    for line in text.splitlines():
        head = _HEADING.match(line)
        if head:
            version = head.group(1)
            continue
        item = _ITEM.match(line)
        if version and item:
            out.append(Entry(version, item.group(1)))
    return out


def newer(entries: list[Entry], since: str | None) -> list[Entry]:
    """Entries above `since`; with no baseline, only the newest version's."""
    if not entries:
        return []
    if since is None:
        top = max((e.version for e in entries), key=vkey)
        return [e for e in entries if e.version == top]
    floor = vkey(since)
    return [e for e in entries if vkey(e.version) > floor]


def fetch(url: str = CHANGELOG_URL, opener=urllib.request.urlopen) -> str:
    with opener(url, timeout=FETCH_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8")


def installed(run=subprocess.run) -> str | None:
    """`claude --version`'s version, or None when there is no claude to ask."""
    try:
        got = run(["claude", "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    m = _SEMVER.search(got.stdout or "") if got.returncode == 0 else None
    return m.group(1) if m else None


def setup(settings_path: Path, version: str | None) -> dict:
    """What of the local Claude Code setup a changelog entry could touch."""
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    hooks = raw.get("hooks") if isinstance(raw.get("hooks"), dict) else {}
    plugins = raw.get("enabledPlugins") if isinstance(raw.get("enabledPlugins"), dict) else {}
    return {"settings_keys": sorted(raw),
            "hook_events": sorted(hooks),
            "plugins": sorted(k for k, on in plugins.items() if on),
            "version": version}


def summary(s: dict) -> str:
    return "\n".join([
        f"installed Claude Code version: {s.get('version') or 'unknown'}",
        f"settings.json keys: {', '.join(s['settings_keys']) or 'none'}",
        f"hook events in use: {', '.join(s['hook_events']) or 'none'}",
        f"enabled plugins: {', '.join(s['plugins']) or 'none'}",
    ])


def terms(s: dict) -> set[str]:
    """Lowercased words the keyword fallback looks for."""
    got = set()
    for name in [*s["settings_keys"], *s["hook_events"], *(p.split("@")[0] for p in s["plugins"])]:
        got.add(name.lower())
        got.update(w.lower() for w in _WORD.findall(name))
    if s["hook_events"]:
        got.update({"hook", "hooks"})
    if s["plugins"]:
        got.update({"plugin", "plugins"})
    return got


def keyword(entry: Entry, words: set[str]) -> bool:
    found = {w.lower() for w in _WORD.findall(entry.text)}
    return bool(found & words)


def local_model(text: str, context: str) -> bool:
    """The decide lane's adopted model; raises when it cannot answer (busy, down, unparsable)."""
    from harness import delegate
    got = delegate.decide(QUESTION + text, SCHEMA, context=context)
    # The decide lane answers a boolean field as the string "true" or "false".
    return str(got["answers"]["relevant"]).strip().lower() == "true"


def classify(entries: list[Entry], s: dict, model=local_model) -> tuple[list[bool], str]:
    """(relevant flags, how they were decided); the keyword match once the model cannot answer."""
    context, words, flags = summary(s), terms(s), []
    for i, e in enumerate(entries):
        try:
            flags.append(bool(model(e.text, context)))
        except Exception as exc:  # noqa: BLE001
            why = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else type(exc).__name__
            flags.extend(keyword(x, words) for x in entries[i:])
            return flags, f"keyword match against the setup (local model unavailable: {why})"
    return flags, "local decide model"


def last_seen(conn) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (LAST_KEY,)).fetchone()
    return row[0] if row else None


def record(conn, version: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (LAST_KEY, version))
    conn.commit()


def digest(conn, changelog: str, s: dict, model=local_model, since: str | None = None,
           keep: bool = True) -> dict:
    """The digest of entries newer than `since` (else the recorded version, else the installed one)."""
    base = since or last_seen(conn) or s.get("version")
    entries = newer(parse(changelog), base)
    if not entries:
        return {"since": base, "latest": base, "versions": [], "relevant": [], "other": [],
                "classifier": None}
    flags, how = classify(entries, s, model)
    latest = max((e.version for e in entries), key=vkey)
    if keep:
        record(conn, latest)
    return {"since": base, "latest": latest,
            "versions": sorted({e.version for e in entries}, key=vkey, reverse=True),
            "relevant": [e.as_dict() for e, f in zip(entries, flags) if f],
            "other": [e.as_dict() for e, f in zip(entries, flags) if not f],
            "classifier": how}


def render(d: dict) -> list[str]:
    if not d["versions"]:
        return []
    lines = [f"Claude Code {d['since'] or '(no baseline)'} -> {d['latest']}: "
             f"{len(d['versions'])} new version(s) ({', '.join(d['versions'])})",
             f"classified by: {d['classifier']}", "",
             f"Relevant to how we run ({len(d['relevant'])}):"]
    lines += [f"  {e['version']:<10} {e['text']}" for e in d["relevant"]] or ["  none"]
    lines += ["", f"The rest ({len(d['other'])}):"]
    lines += [f"  {e['version']:<10} {e['text']}" for e in d["other"]] or ["  none"]
    return lines


def notify(d: dict, run=subprocess.run) -> str | None:
    """A desktop notification only when something relevant arrived; None when nothing was sent."""
    if not d["relevant"]:
        return None
    from harness import watchdog
    n = len(d["relevant"])
    return watchdog.desktop(NOTIFY_TITLE, f"{n} Claude Code change(s) relevant to this setup, "
                            f"up to {d['latest']}", d["relevant"][0]["text"], run)
