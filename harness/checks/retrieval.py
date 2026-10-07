"""Scoring a ranking against labelled relevant documents: recall@k and nDCG@10. #563."""
from __future__ import annotations

import json
import math

from harness.checks.base import CheckResult

NDCG_AT = 10
DEFAULT_K = 5


def _first_seen(ranking) -> list[str]:
    seen, out = set(), []
    for doc in ranking:
        doc = str(doc)
        if doc not in seen:
            seen.add(doc)
            out.append(doc)
    return out


def recall_at(ranking, relevant: set, k: int) -> float:
    """Share of the relevant documents in the first k, duplicates counted once."""
    return len(set(_first_seen(ranking)[:k]) & set(relevant)) / len(relevant)


def ndcg_at(ranking, relevant: set, k: int = NDCG_AT) -> float:
    """Binary-gain nDCG over the first k."""
    gain = sum(1 / math.log2(i + 2) for i, doc in enumerate(_first_seen(ranking)[:k])
               if doc in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return gain / ideal


def parse(text: str) -> list[str]:
    """The ranking from {"ranking": [...]} or a bare list; ValueError otherwise."""
    got = json.loads(text)
    if isinstance(got, dict):
        got = got.get("ranking")
    if not isinstance(got, list):
        raise ValueError("no ranking list in the output")
    return [str(x) for x in got]


def check(text: str, relevant, k: int = DEFAULT_K) -> CheckResult:
    try:
        ranking = parse(text)
    except ValueError as exc:
        return CheckResult(False, f"no ranking could be read: {exc}")
    rel = set(relevant)
    recall = recall_at(ranking, rel, k)
    out = CheckResult(recall == 1.0, "")
    out.metrics = {"retrieval_recall": round(recall, 4),
                   "retrieval_ndcg": round(ndcg_at(ranking, rel), 4)}
    if not out.ok:
        out.reason = (f"recall@{k} {recall:.2f}: missed "
                      f"{sorted(rel - set(_first_seen(ranking)[:k]))}; top {k} was "
                      f"{_first_seen(ranking)[:k]}")
    return out
