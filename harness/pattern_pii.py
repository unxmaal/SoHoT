"""Patterns for personal data: the pii lane's incumbent, with no weights. #564.

    python -m harness.pattern_pii --text "..." --out spans.json

It finds what has a shape (an email, a number, an address on the wire, a key)
and is blind to names and street addresses, which is the gap a model must close.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PATTERNS = {
    "email": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "url": r"https?://[^\s,;]+[^\s,;.]",
    "ipv4": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "iban": r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b",
    "card": r"\b(?:\d{4}[ -]?){3}\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "phone": r"(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?)?\d{2,4}[ .-]\d{3,4}[ .-]?\d{0,4}\b",
    "key": r"\b(?:sk|pk|ghp|xox[bp])[-_][\w-]{12,}\b",
}


def find(text: str) -> list[list]:
    """[start, end, kind] for each match, longest first where two overlap."""
    hits = sorted(((m.start(), m.end(), kind) for kind, p in PATTERNS.items()
                   for m in re.finditer(p, text)), key=lambda h: (h[0], -(h[1] - h[0])))
    out: list[list] = []
    for s, e, kind in hits:
        if out and s < out[-1][1]:
            continue
        out.append([s, e, kind])
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--text", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    Path(a.out).write_text(json.dumps({"spans": find(a.text)}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
