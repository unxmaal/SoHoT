"""Span recall on real exploratory Reads: gold is what the agent later used from the file. Transcripts are read in place; rows keep numbers only. #1336."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

from harness import spans

KINDS = ("python", "markdown", "tests")
#: The issue's bars: spans hold at least this share of the gold.
RECALL_BAR = 0.90
REDO_BAR = 0.20
MIN_GOLD = 2
#: A file line this long, stripped, counts as gold when a later input holds it.
GOLD_LINE_CHARS = 30
QUESTION_CHARS = 500
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_LATER = ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash")


@dataclass
class Case:
    id: str
    kind: str
    question: str
    text: str
    idents: list
    lines: list


def code_like(word: str) -> bool:
    return "_" in word or bool(re.search(r"[a-z][A-Z]", word)) or (word.isupper() and len(word) >= 4)


def _blocks(rec: dict) -> list:
    content = (rec.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _strings(inp: dict) -> str:
    return "\n".join(str(v) for k, v in sorted(inp.items()) if isinstance(v, str) and k != "description")


def _said(recs: list[dict], i: int, role: str) -> str:
    """The nearest text at or before record i from `role`: the agent's intent, or the task it was given."""
    for j in range(i, -1, -1):
        r = recs[j]
        if r.get("type") != role or r.get("toolUseResult") or r.get("isMeta"):
            continue
        content = (r.get("message") or {}).get("content")
        text = content if isinstance(content, str) else " ".join(
            str(b.get("text") or "") for b in _blocks(r) if b.get("type") == "text")
        if text.strip():
            return " ".join(text.split())
    return ""


def question(recs: list[dict], i: int, name: str, tally: dict | None = None) -> str:
    """What the agent wanted from the file, as near as the transcript says: its own words, then its task."""
    said, task = _said(recs, i, "assistant"), _said(recs, i, "user")
    ask = f"Quote what an engineer doing this task needs from {name}: definitions, signatures, constants, steps."
    if tally is not None and max(len(said), len(task)) > QUESTION_CHARS:
        tally["long"] = tally.get("long", 0) + 1
    said, task = said[-QUESTION_CHARS:], task[:QUESTION_CHARS]
    return " ".join(x for x in (ask, f"They said: {said}" if said else "", f"The task: {task}" if task else "") if x)


def gold(text: str, before: str, after: str) -> tuple[list, list]:
    """Code-like identifiers and long lines of `text` that later inputs hold and nothing before the Read did."""
    used, known = set(_IDENT.findall(after)), set(_IDENT.findall(before))
    idents = sorted({w for w in _IDENT.findall(text) if code_like(w) and w in used and w not in known})
    lines = sorted({s for s in (r.strip() for r in text.splitlines())
                    if len(s) >= GOLD_LINE_CHARS and s in after and s not in before})
    return idents, lines


def stream_cases(recs: list[dict], since: float | None, tag: str, tally: dict | None = None) -> list[Case]:
    from harness import context_class as cc
    from harness.context_report import _epoch
    edits, _, _ = cc._look_ahead(recs)
    results = {}
    for rec in recs:
        file = (rec.get("toolUseResult") or {}).get("file") if isinstance(rec.get("toolUseResult"), dict) else None
        for b in _blocks(rec):
            if b.get("type") == "tool_result" and isinstance(file, dict):
                results[str(b.get("tool_use_id") or "")] = file
    inputs = [(i, _strings(b.get("input") or {})) for i, r in enumerate(recs) if r.get("type") == "assistant"
              for b in _blocks(r) if b.get("type") == "tool_use" and isinstance(b.get("input"), dict)
              and b.get("name") in _LATER]
    users = [(i, json.dumps(r.get("message"), ensure_ascii=False)) for i, r in enumerate(recs)
             if r.get("type") == "user" and not r.get("toolUseResult")]
    out = []
    for i, rec in enumerate(recs):
        if rec.get("type") != "assistant":
            continue
        at = _epoch(rec.get("timestamp"))
        if since is not None and (at is None or at < since):
            continue
        for b in _blocks(rec):
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            if b.get("type") != "tool_use" or b.get("name") != "Read" or inp.get("offset") or inp.get("limit"):
                continue
            path = os.path.normpath(str(inp.get("file_path") or ""))
            file = results.get(str(b.get("id") or ""))
            if (not file or cc.file_kind(path) not in KINDS or edits.get(path, -1) > i
                    or file.get("startLine") not in (None, 1) or file.get("numLines") != file.get("totalLines")):
                continue
            text = str(file.get("content") or "")
            if len(text) < spans.MIN_CHARS:
                continue
            before = "\n".join(s for j, s in inputs + users if j < i)
            after = "\n".join(s for j, s in inputs if j > i)
            idents, lines = gold(text, before, after)
            if len(idents) + len(lines) < MIN_GOLD:
                if tally is not None:
                    tally["thin"] = tally.get("thin", 0) + 1
                continue
            asked = question(recs, i, os.path.basename(path), tally)
            cid = hashlib.sha256(f"{tag}:{b.get('id')}".encode()).hexdigest()[:12]
            out.append(Case(cid, cc.file_kind(path), asked, text, idents, lines))
    return out


def cases(root: Path, since: float) -> list[Case]:
    from harness import context_report as cr
    from harness import cuts
    out, tally = [], {}
    for n, (recs, _usage) in enumerate(cr.streams(root, since)):
        out += stream_cases(recs, since, f"{n}:{recs[0].get('sessionId', '') if recs else ''}", tally)
    if tally.get("thin"):
        cuts.cut("evals/spans_recall.py:MIN_GOLD", "Reads with too little gold to score", kept=len(out),
                 dropped=tally["thin"])
    if tally.get("long"):
        cuts.cut("evals/spans_recall.py:QUESTION_CHARS", "eval questions cut to length", kept=len(out),
                 dropped=tally["long"])
    return out


def score(case: Case, got: spans.Result) -> dict:
    body = got.body
    quoted = {r.split("\t", 1)[1].strip() for r in body.splitlines() if "\t" in r}
    words = set(_IDENT.findall(body))
    found = sum(w in words for w in case.idents) + sum(s in quoted for s in case.lines)
    return {"id": case.id, "kind": case.kind, "chars": len(case.text), "mode": got.mode, "code": got.code,
            "gold": len(case.idents) + len(case.lines), "found": found, "verbatim": spans.verbatim(case.text, body),
            "returned_chars": len(body), "calls": got.calls, "seconds": got.seconds}


def summary(rows: list[dict]) -> dict:
    sp = [r for r in rows if r["mode"] == spans.SPANS]
    gold_n, found_n = sum(r["gold"] for r in sp), sum(r["found"] for r in sp)
    codes: dict[str, int] = {}
    for r in rows:
        if r["mode"] == spans.WHOLE:
            codes[r["code"]] = codes.get(r["code"], 0) + 1
    recall = (found_n / gold_n) if gold_n else None
    verbatim = sum(r["verbatim"] for r in rows)
    saved = sum(r["chars"] - r["returned_chars"] for r in sp) // 4
    whole_chars = sum(r["chars"] for r in rows) // 4
    return {"cases": len(rows), "spans": len(sp), "whole": len(rows) - len(sp), "whole_by": codes,
            "recall": recall, "gold": gold_n, "found": found_n, "verbatim": verbatim,
            "saved_tokens": saved, "read_tokens": whole_chars,
            "passes": bool(sp) and recall is not None and recall >= RECALL_BAR and verbatim == len(rows)}


def run(found: list[Case], answer, out: Path, n: int = 100, seed: int = 1336, progress=None) -> dict:
    """Score `answer(text, question) -> spans.Result` on n sampled cases; rows (numbers only) go to out/results.jsonl."""
    picked = sorted(found, key=lambda c: c.id)
    picked = random.Random(seed).sample(picked, min(n, len(picked)))
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(out / "results.jsonl", "w", encoding="utf-8") as fh:
        for case in picked:
            row = score(case, answer(case.text, case.question))
            rows.append(row)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if progress:
                progress(row)
    return {**summary(rows), "available": len(found)}
