"""decide: five SQuAD 2.0 questions per paragraph, answerable or not, as one multi-field case. #603."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from evals.importers import CASES, Imported, squad2

LANE = "decide"
SOURCE, DATASET, URL = squad2.SOURCE, squad2.DATASET, squad2.URL
LICENSE, REVISION = squad2.LICENSE, squad2.REVISION
QUESTIONS = 5
N = 440
TRANSFORM = (f"first {QUESTIONS} questions of a paragraph in sha256(id) order, kept only when "
             "they mix both answers; true when the human answer list is non-empty")


def taken(root: Path = CASES) -> set[str]:
    """SQuAD records the lane's hand-generated cases already ask about."""
    out: set[str] = set()
    for p in sorted((Path(root) / LANE).glob("*.yaml")):
        att = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("attribution") or {}
        if "squad" in str(att.get("dataset", "")).lower():
            out |= {r.strip() for r in str(att.get("record", "")).split(",") if r.strip()}
    return out


def select(data: dict, n: int = N, exclude=frozenset()) -> list[dict]:
    """Rows: qualifying paragraphs in sha256(pid) order, each with its five questions."""
    rows = []
    for para in squad2.shuffled(squad2.paragraphs(data), lambda p: p.pid):
        if any(f"squad2-{q.qid}" in exclude for q in para.qas):
            continue
        head = squad2.shuffled(para.qas, lambda q: q.qid)[:QUESTIONS]
        if len(head) < QUESTIONS or not 0 < sum(q.answerable for q in head) < QUESTIONS:
            continue
        rows.append({"pid": para.pid, "context": para.context,
                     "questions": [{"qid": q.qid, "question": q.question,
                                    "answerable": q.answerable} for q in head]})
        if len(rows) >= n:
            break
    return rows


def fetch() -> list[dict]:
    return select(squad2.load(), N, taken())


def convert(row: dict) -> Imported:
    qs = row["questions"]
    schema = {f"q{k}": {"type": "boolean", "description": (
        f"True only if the paragraph itself states the answer to: {q['question']}")}
        for k, q in enumerate(qs, 1)}
    case = {"id": f"check-squad2-{qs[0]['qid']}", "modality": "decide",
            "prompt": "Check which of these questions the paragraph answers.",
            "context": row["context"], "params": {"schema": schema},
            "assert": {"answers": {f"q{k}": q["answerable"] for k, q in enumerate(qs, 1)}},
            "attribution": squad2.attribution(
                sys.modules[__name__], ", ".join(f"squad2-{q['qid']}" for q in qs),
                f"paragraph {row['pid']}; {TRANSFORM}")}
    return Imported(case)


def _reply(answers: dict) -> str:
    return json.dumps({"answers": answers})


RESPONDERS = {
    "reference": lambda c: _reply(c.assertions["answers"]),
    "all_true": lambda c: _reply({k: True for k in c.assertions["answers"]}),
    "all_false": lambda c: _reply({k: False for k in c.assertions["answers"]}),
    "shuffled": lambda c: _reply(squad2.neighbour(c)["assert"]["answers"]),
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
