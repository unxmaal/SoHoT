"""extract: one answerable SQuAD 2.0 question per paragraph, answered by an exact span. #603."""
from __future__ import annotations

import sys

from evals.importers import Imported, squad2

LANE = "extract"
SOURCE, DATASET, URL = squad2.SOURCE, squad2.DATASET, squad2.URL
LICENSE, REVISION = squad2.LICENSE, squad2.REVISION
MAX_WORDS = 5
N = 440
PROMPT = ("Answer the question from the text. Reply with only the answer, copied "
          "exactly as it appears in the text, nothing else.\n\nQuestion: {question}")
TRANSFORM = (f"first answerable question in sha256(id) order whose every human answer is at "
             f"most {MAX_WORDS} words; any human answer, exactly, passes")


def _usable(q, context: str) -> bool:
    return q.answerable and all(len(a.split()) <= MAX_WORDS and a in context
                                for a in q.answers)


def select(data: dict, n: int = N) -> list[dict]:
    rows = []
    for para in squad2.shuffled(squad2.paragraphs(data), lambda p: p.pid):
        q = next((q for q in squad2.shuffled(para.qas, lambda q: q.qid)
                  if _usable(q, para.context)), None)
        if q is None:
            continue
        rows.append({"pid": para.pid, "context": para.context, "qid": q.qid,
                     "question": q.question, "answers": list(q.answers)})
        if len(rows) >= n:
            break
    return rows


def fetch() -> list[dict]:
    return select(squad2.load(), N)


def convert(row: dict) -> Imported:
    case = {"id": f"extract-squad2-{row['qid']}", "modality": "extract",
            "prompt": PROMPT.format(question=row["question"]), "context": row["context"],
            "assert": {"equals": list(row["answers"])},
            "attribution": squad2.attribution(sys.modules[__name__], f"squad2-{row['qid']}",
                                              f"paragraph {row['pid']}; {TRANSFORM}")}
    return Imported(case)


RESPONDERS = {
    "reference": lambda c: c.assertions["equals"][0],
    "unknown": lambda c: "unknown",
    "echo": lambda c: c.context,
    "shuffled": lambda c: squad2.neighbour(c)["assert"]["equals"][0],
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
