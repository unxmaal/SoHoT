"""retrieval: a SQuAD 2.0 question ranks its own article's paragraphs; the gold one must come first. #603."""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

from evals.importers import Imported, squad2

LANE = "retrieval"
SOURCE, DATASET, URL = squad2.SOURCE, squad2.DATASET, squad2.URL
LICENSE, REVISION = squad2.LICENSE, squad2.REVISION
#: bm25 passes 0.96 at k 5, a saturated holdout; 0.78 at k 1.
K = 1
N = 580
TRANSFORM = ("first answerable question of the paragraph in sha256(id) order; corpus is every "
             "paragraph of its article; relevant is the paragraph the question was written for")


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def select(data: dict, n: int = N) -> list[dict]:
    """Rows: articles in sha256(title) order, one question per paragraph, each row carrying its corpus."""
    by: dict[str, list] = {}
    for para in squad2.paragraphs(data):
        by.setdefault(para.article, []).append(para)
    rows = []
    for article in squad2.shuffled(by, lambda a: a):
        if len(rows) >= n:
            break
        corpus = [{"id": f"{slug(article)}-{p.index:02d}", "text": p.context} for p in by[article]]
        for para in squad2.shuffled(by[article], lambda p: p.pid):
            q = next((q for q in squad2.shuffled(para.qas, lambda q: q.qid) if q.answerable), None)
            if q is None:
                continue
            rows.append({"pid": para.pid, "qid": q.qid, "question": q.question,
                         "corpus_file": f"{slug(article)}.jsonl", "corpus": corpus,
                         "relevant": f"{slug(article)}-{para.index:02d}"})
            if len(rows) >= n:
                break
    return rows


def fetch() -> list[dict]:
    return select(squad2.load(), N)


def convert(row: dict) -> Imported:
    case = {"id": f"retrieval-squad2-{row['qid']}", "modality": "retrieval",
            "prompt": row["question"], "input_file": row["corpus_file"],
            "assert": {"relevant": [row["relevant"]], "k": K},
            "attribution": squad2.attribution(sys.modules[__name__], f"squad2-{row['qid']}",
                                              f"question of paragraph {row['pid']}; {TRANSFORM}")}
    corpus = "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in row["corpus"])
    return Imported(case, files=((row["corpus_file"], corpus.encode("utf-8")),))


def _ids(case) -> list[str]:
    return [json.loads(line)["id"] for line in
            Path(case.input_file).read_text(encoding="utf-8").splitlines() if line]


def _ranking(ids) -> str:
    return json.dumps({"ranking": list(ids)})


RESPONDERS = {
    "reference": lambda c: _ranking(list(c.assertions["relevant"]) + _ids(c)),
    "corpus_order": lambda c: _ranking(_ids(c)),
    "shuffled": lambda c: _ranking(random.Random(c.id).sample(_ids(c), len(_ids(c)))),
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
