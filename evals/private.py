"""Where a private case's text or content digest turns up outside its local tree. #654."""
from __future__ import annotations

import json
import re
from pathlib import Path

#: Shorter fragments than this are common phrases, not a case's text.
MIN_FRAGMENT = 24
_SPEAKER = re.compile(r"^\s*\[\d+\]\s*[^:]{1,64}:\s*")


def fragments(cases) -> set[str]:
    """Each private case's transcript lines, minus the speaker tag, and its reviewed claims."""
    out: set[str] = set()
    for c in cases:
        if not getattr(c, "private", False):
            continue
        texts = [_SPEAKER.sub("", line) for line in f"{c.prompt}\n{c.context}".splitlines()]
        texts += [str(r.get("claim") or "") for r in (c.assertions.get("reviews") or [])]
        out |= {t.strip() for t in texts if len(t.strip()) >= MIN_FRAGMENT}
    return out


def _forms(fragment: str) -> tuple[str, ...]:
    return (fragment, json.dumps(fragment)[1:-1], repr(fragment)[1:-1])


def found_in(text: str, frags) -> bool:
    return any(form in text for f in frags for form in _forms(f))


def leaks(roots, cases) -> list[tuple[str, str]]:
    """(file, why) for every file under `roots` holding a private case's text or digest."""
    from evals.core import case_digest, load_case
    private = [c for c in cases if getattr(c, "private", False)]
    if not private:
        return []
    frags = fragments(private)
    digests = {case_digest(c) for c in private}
    out = []
    for root in map(Path, roots):
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if found_in(text, frags):
                out.append((str(path), "private case text"))
                continue
            if path.suffix == ".yaml":
                try:
                    got = case_digest(load_case(path))
                except Exception:  # noqa: BLE001
                    continue
                if got in digests:
                    out.append((str(path), "private case digest"))
    return out


def withhold_detail(row, case) -> None:
    """Replace a private case's row detail when it quotes the case. #654."""
    if getattr(case, "private", False) and row.detail and found_in(row.detail, fragments([case]) | _lines(case)):
        row.detail = f"detail withheld: it quoted private case {case.id}"


def _lines(case) -> set[str]:
    return {line.strip() for line in f"{case.prompt}\n{case.context}".splitlines()
            if len(line.strip()) >= MIN_FRAGMENT}


def local_cases():
    """This machine's private cases, or [] where it has none."""
    from evals.core import load_cases, local_root
    root = local_root()
    return load_cases(root, private=True) if root.is_dir() else []
