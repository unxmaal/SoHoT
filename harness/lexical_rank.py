"""Okapi BM25 over a JSONL corpus: the retrieval lane's incumbent, with no weights. #563.

    python -m harness.lexical_rank --query Q --corpus corpus.jsonl --out ranking.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

K1, B = 1.5, 0.75
_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _WORD.findall(str(text).lower())


def rank(query: str, docs: list[dict], k1: float = K1, b: float = B) -> list[str]:
    """Document ids, best first; ties keep corpus order."""
    bodies = [tokens(d["text"]) for d in docs]
    n = len(bodies)
    avg = sum(len(t) for t in bodies) / n if n else 0.0
    df: dict[str, int] = {}
    for t in bodies:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    terms = set(tokens(query))

    def score(body: list[str]) -> float:
        total = 0.0
        for w in terms:
            f = body.count(w)
            if not f:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            total += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(body) / avg))
        return total
    scored = [(-score(body), i) for i, body in enumerate(bodies)]
    return [docs[i]["id"] for _, i in sorted(scored)]


def load(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--query", required=True)
    p.add_argument("--corpus", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    Path(a.out).write_text(json.dumps({"ranking": rank(a.query, load(a.corpus))}),
                           encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
