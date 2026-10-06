"""Deterministic, real-looking repo padding for the agent lane's long-context cases. #474.

Seeded by the case id, so the same case always gets the same bytes and the
cases digest pins it. No external data.
"""
from __future__ import annotations

import hashlib
import random

#: Rough chars per token for Python source; the case asks for tokens.
CHARS_PER_TOKEN = 4
PAD_DIR = "vendor"

_NOUNS = ("account", "ledger", "invoice", "shipment", "carrier", "route",
          "warehouse", "bin", "pallet", "order", "customer", "region",
          "tariff", "quote", "batch", "manifest", "parcel", "label", "zone",
          "supplier", "contract", "rate", "schedule", "slot", "dock", "audit")
_VERBS = ("load", "parse", "merge", "split", "apply", "compute", "render",
          "resolve", "validate", "lookup", "summarize", "reconcile", "allocate",
          "estimate", "normalize", "group", "rank", "filter", "flush", "stage")
_ADJ = ("pending", "active", "stale", "primary", "fallback", "nightly",
        "partial", "weighted", "regional", "cached", "draft", "final")


def _ident(r: random.Random, *pools) -> str:
    return "_".join(r.choice(p) for p in pools)


def _function(r: random.Random) -> str:
    name = _ident(r, _VERBS, _ADJ, _NOUNS)
    a, b = r.sample(_NOUNS, 2)
    n = r.randint(2, 9)
    body = r.choice([
        f"    total = 0\n    for item in {a}s:\n        if item.get(\"{b}\") is None:\n"
        f"            continue\n        total += int(item[\"{b}\"]) * {n}\n    return total\n",
        f"    out = {{}}\n    for item in {a}s:\n        key = item.get(\"{b}\", \"unknown\")\n"
        f"        out.setdefault(key, []).append(item)\n    return out\n",
        f"    if not {a}s:\n        return []\n    ranked = sorted({a}s, key=lambda x: x.get(\"{b}\", 0))\n"
        f"    return ranked[:{n}]\n",
        f"    seen = set()\n    kept = []\n    for item in {a}s:\n        tag = (item.get(\"{b}\"), item.get(\"id\"))\n"
        f"        if tag in seen:\n            continue\n        seen.add(tag)\n        kept.append(item)\n    return kept\n",
    ])
    return (f"def {name}({a}s, {b}_limit={n}):\n"
            f"    \"\"\"{r.choice(_VERBS).capitalize()} the {r.choice(_ADJ)} {a} records "
            f"by {b}.\"\"\"\n{body}\n")


def _class(r: random.Random) -> str:
    noun = r.choice(_NOUNS)
    name = "".join(w.capitalize() for w in (r.choice(_ADJ), noun)) + "Store"
    fields = r.sample(_NOUNS, 3)
    init = "".join(f"        self.{f} = {f}\n" for f in fields)
    return (f"class {name}:\n    \"\"\"Holds {noun} rows keyed by {fields[0]}.\"\"\"\n\n"
            f"    def __init__(self, {', '.join(fields)}):\n{init}        self._rows = {{}}\n\n"
            f"    def put(self, key, row):\n        self._rows[key] = dict(row)\n\n"
            f"    def get(self, key, default=None):\n        return self._rows.get(key, default)\n\n"
            f"    def __len__(self):\n        return len(self._rows)\n\n\n")


def _module(r: random.Random) -> str:
    parts = [f"\"\"\"{r.choice(_NOUNS).capitalize()} helpers for the "
             f"{r.choice(_ADJ)} {r.choice(_NOUNS)} pipeline.\"\"\"\n\n"]
    for _ in range(r.randint(3, 6)):
        parts.append(_class(r) if r.random() < 0.3 else _function(r) + "\n")
    return "".join(parts)


def padding(case_id: str, tokens: int) -> dict[str, str]:
    """{relative path: source} totalling about `tokens` tokens."""
    if tokens <= 0:
        return {}
    seed = int.from_bytes(hashlib.sha256(case_id.encode("utf-8")).digest()[:8], "big")
    r = random.Random(seed)
    budget = tokens * CHARS_PER_TOKEN
    out: dict[str, str] = {f"{PAD_DIR}/__init__.py": ""}
    used = 0
    while used < budget:
        name = f"{PAD_DIR}/{_ident(r, _NOUNS, _VERBS)}_{len(out)}.py"
        text = _module(r)
        out[name] = text
        used += len(text)
    return out


def snapshot(files: dict[str, str]) -> str:
    """The repo as one block of text, the way an agent client attaches files."""
    return "\n".join(f"=== {path} ===\n{text}" for path, text in sorted(files.items()))
