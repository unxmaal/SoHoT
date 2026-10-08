"""Claims lane scoring: schema validation, then emitted claims matched to human-reviewed ones. #654.

A reason never quotes case or reply text: claims cases are private and reasons reach the store.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from harness.checks.base import CheckResult

VERDICTS = ("good", "not_useful", "made_up", "wrong")
NEGATIVE = ("made_up", "wrong")

#: Shared-word similarity at or above which an emitted claim is the reviewed one it overlaps.
MATCH_THRESHOLD = 0.5
#: Share of a case's good reviewed claims a reply must recover to pass.
MIN_RECALL = 0.5

#: The reply schema, written by evals.claims_import from infovore's export: the lane keeps no copy. #659.
SCHEMA_FILE = "schema.json"


class NoSchema(ValueError):
    """No claims schema has been imported on this machine."""


def schema_path(root=None) -> Path:
    """Where the imported schema lives: beside the local claims cases unless `root` says otherwise."""
    if root is not None:
        return Path(root) / SCHEMA_FILE
    from harness import paths
    return paths.home() / "cases" / "claims" / SCHEMA_FILE


def served_schema(root=None) -> dict:
    """The schema the claims lane serves, as the last import wrote it."""
    path = schema_path(root)
    if not path.is_file():
        raise NoSchema("no claims schema imported; run `uv run python -m evals.claims_import` first")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise NoSchema(f"{path.name} is not a JSON object")
    return data


def write_schema(out, schema: dict) -> Path:
    path = Path(out) / SCHEMA_FILE
    path.write_text(json.dumps(schema, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return path


_WORD = re.compile(r"[^a-z0-9]+")
#: How far under the threshold an unmatched pair counts as one the threshold decided.
_NEAR_MISS = 0.15


def response_format(schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "claims", "strict": True, "schema": schema}}


def validate_case(system, schema, reviews, expect_empty) -> None:
    """Raise ValueError naming what is wrong with a case's system, schema or reviews."""
    from jsonschema import Draft202012Validator, SchemaError
    if not isinstance(system, str) or not system.strip():
        raise ValueError("a claims case needs params.system, the prompt it is asked with")
    if not isinstance(schema, dict):
        raise ValueError("a claims case needs params.schema, the reply schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"params.schema is not a JSON schema: {exc.message}") from exc
    if not isinstance(reviews, list):
        raise ValueError("a claims case needs assert.reviews, a list")
    for n, r in enumerate(reviews):
        if not isinstance(r, dict) or not isinstance(r.get("user"), str) or not isinstance(r.get("claim"), str):
            raise ValueError(f"review {n} needs a user and a claim")
        if r.get("verdict") not in VERDICTS:
            raise ValueError(f"review {n} has verdict {r.get('verdict')!r}; known: {', '.join(VERDICTS)}")
        refs = r.get("refs")
        if not isinstance(refs, list) or not refs or not all(isinstance(x, int) for x in refs):
            raise ValueError(f"review {n} needs refs, a non-empty list of line numbers")
    if expect_empty and reviews:
        raise ValueError("an expect_empty case carries no reviews")
    if not expect_empty and not reviews:
        raise ValueError("a case with no reviews must say expect_empty: true")


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.split(str(text).lower()) if t]


def similarity(a: str, b: str) -> float:
    """Dice coefficient over word multisets, in [0, 1]."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 0.0
    common = sum((Counter(ta) & Counter(tb)).values())
    return 2 * common / (len(ta) + len(tb))


def match(emitted: list, reviewed: list[dict], threshold: float) -> list[tuple[int, int, float]]:
    """One-to-one (emitted index, reviewed index, similarity): same user, refs overlap, best first."""
    pairs = []
    for i, (user, claim, refs) in enumerate(emitted):
        for j, r in enumerate(reviewed):
            if user != r["user"] or not set(refs) & set(r["refs"]):
                continue
            sim = similarity(claim, r["claim"])
            if sim >= threshold:
                pairs.append((sim, i, j))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    used_i, used_j, out = set(), set(), []
    for sim, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        out.append((i, j, sim))
    return sorted(out)


def _near_miss(emitted: list, reviews: list[dict], pairs: list) -> bool:
    """Whether an unmatched claim missed an unmatched good review by the threshold alone."""
    used_i, used_j = {i for i, _, _ in pairs}, {j for _, j, _ in pairs}
    floor = MATCH_THRESHOLD - _NEAR_MISS
    for i, (user, claim, refs) in enumerate(emitted):
        for j, r in enumerate(reviews):
            if i in used_i or j in used_j or r["verdict"] != "good":
                continue
            if user == r["user"] and set(refs) & set(r["refs"]) and similarity(claim, r["claim"]) >= floor:
                return True
    return False


def parse(text, schema: dict) -> list[tuple] | None:
    """The reply's claims as (user, claim, refs), or None when it is not the schema's JSON."""
    from jsonschema import Draft202012Validator
    try:
        got = json.loads(str(text or "").strip())
    except ValueError:
        return None
    if not Draft202012Validator(schema).is_valid(got):
        return None
    rows = got.get("c") if isinstance(got, dict) else None
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows:
        if not (isinstance(row, list) and len(row) == 3 and isinstance(row[2], list)):
            return None
        out.append((str(row[0]), str(row[1]), [int(x) for x in row[2]]))
    return out


def check(artifact, schema: dict, reviews: list[dict], expect_empty: bool = False) -> CheckResult:
    emitted = parse(artifact, schema)
    if emitted is None:
        out = CheckResult(False, "reply does not validate against the case's schema")
        out.metrics = {"claims_schema_valid": 0, "claims_judge_calibrated": 0}
        return out
    if expect_empty:
        kept = int(not emitted)
        out = CheckResult(bool(kept), "" if kept else f"expected no claims, emitted {len(emitted)}")
        out.metrics = {"claims_schema_valid": 1, "claims_emitted": len(emitted),
                       "claims_empty_kept": kept, "claims_empty_cases": 1,
                       "claims_empty_rate": float(kept), "claims_judge_calibrated": 0}
        return out
    pairs = match(emitted, reviews, MATCH_THRESHOLD)
    verdicts = Counter(reviews[j]["verdict"] for _, j, _ in pairs)
    good_total = sum(1 for r in reviews if r["verdict"] == "good")
    good = verdicts["good"]
    bad = sum(verdicts[v] for v in NEGATIVE)
    # A case whose reviews hold no good claim is passed by avoiding the rejected ones.
    recall = good / good_total if good_total else 1.0
    metrics = {"claims_schema_valid": 1, "claims_emitted": len(emitted),
               "claims_reviewed_matched": len(pairs), "claims_unreviewed": len(emitted) - len(pairs),
               "claims_good_found": good, "claims_good_total": good_total,
               "claims_bad_matched": bad, "claims_recall": round(recall, 4),
               "claims_precision": round(good / len(pairs), 4) if pairs else 0.0,
               "claims_judge_calibrated": 0}
    reason = ""
    if bad:
        named = ", ".join(f"{verdicts[v]} {v}" for v in NEGATIVE if verdicts[v])
        reason = f"emitted claims a reviewer rejected: {named}"
    limit = ""
    if not reason and good_total and recall < MIN_RECALL:
        reason = f"recall {recall:.2f} of {good_total} good claims, under {MIN_RECALL}"
        limit = (f"claims_match_threshold>{MATCH_THRESHOLD:g}"
                 if _near_miss(emitted, reviews, pairs) else f"claims_min_recall>{MIN_RECALL:g}")
    out = CheckResult(not reason, reason, limit=limit)
    out.metrics = metrics
    return out
