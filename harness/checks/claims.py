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

#: What a review without an interface (an export before #661) is scored as.
LEGACY = "legacy"
#: How a reviewer saw the claim; each is its own labelling function, never pooled (RULE #309). #661.
INTERFACES = ("cited-only", "conversation", LEGACY)
#: Per-interface metrics and the direction each ranks in.
PER_INTERFACE = {"recall": "higher", "precision": "higher", "bad_matched": "lower",
                 "unreviewed": "neutral", "pass": "higher", "verbatim": "neutral",
                 "near_miss": "neutral"}
#: Per-interface ratios as (numerator, denominator), summed across cases before dividing.
PER_INTERFACE_RATIOS = {"recall": ("good_found", "good_total"),
                        "precision": ("good_found", "reviewed_matched")}

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


def interface_of(review: dict) -> str:
    return review.get("interface") or LEGACY


def metric(name: str, interface: str) -> str:
    """A per-interface metric's name, as rows and summaries carry it."""
    return f"claims_{name}_{interface.replace('-', '_')}"


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
        if interface_of(r) not in INTERFACES:
            raise ValueError(f"review {n} has interface {r.get('interface')!r}; "
                             f"known: {', '.join(INTERFACES)}")
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


def _near_misses(emitted: list, reviews: list[dict], pairs: list) -> int:
    """How many unmatched good reviews an unmatched claim missed by the threshold alone."""
    used_i, used_j = {i for i, _, _ in pairs}, {j for _, j, _ in pairs}
    floor = MATCH_THRESHOLD - _NEAR_MISS
    return sum(1 for j, r in enumerate(reviews)
               if j not in used_j and r["verdict"] == "good"
               and any(i not in used_i and user == r["user"] and set(refs) & set(r["refs"])
                       and similarity(claim, r["claim"]) >= floor
                       for i, (user, claim, refs) in enumerate(emitted)))


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
    metrics = {"claims_schema_valid": 1, "claims_emitted": len(emitted), "claims_judge_calibrated": 0}
    reason = limit = ""
    by: dict[str, list[dict]] = {}
    for r in reviews:
        by.setdefault(interface_of(r), []).append(r)
    for interface in sorted(by):
        mine, why, knob = _score(emitted, by[interface])
        metrics.update({metric(k, interface): v for k, v in mine.items()})
        if why and not reason:
            reason, limit = f"{interface}: {why}", knob
    out = CheckResult(not reason, reason, limit=limit)
    out.metrics = metrics
    return out


def _score(emitted: list, reviews: list[dict]) -> tuple[dict, str, str]:
    """One interface's metrics, failure reason and deciding knob."""
    pairs = match(emitted, reviews, MATCH_THRESHOLD)
    verdicts = Counter(reviews[j]["verdict"] for _, j, _ in pairs)
    good_total = sum(1 for r in reviews if r["verdict"] == "good")
    good = verdicts["good"]
    bad = sum(verdicts[v] for v in NEGATIVE)
    # A case whose reviews hold no good claim is passed by avoiding the rejected ones.
    recall = good / good_total if good_total else 1.0
    near = _near_misses(emitted, reviews, pairs)
    reason = limit = ""
    if bad:
        named = ", ".join(f"{verdicts[v]} {v}" for v in NEGATIVE if verdicts[v])
        reason = f"emitted claims a reviewer rejected: {named}"
    if not reason and good_total and recall < MIN_RECALL:
        reason = f"recall {recall:.2f} of {good_total} good claims, under {MIN_RECALL}"
        limit = (f"claims_match_threshold>{MATCH_THRESHOLD:g}"
                 if near else f"claims_min_recall>{MIN_RECALL:g}")
    return ({"reviewed_matched": len(pairs), "unreviewed": len(emitted) - len(pairs),
             "good_found": good, "good_total": good_total, "bad_matched": bad,
             "recall": round(recall, 4), "precision": round(good / len(pairs), 4) if pairs else 0.0,
             "pass": int(not reason), "near_miss": near,
             "verbatim": sum(1 for _, _, sim in pairs if sim >= 1.0)}, reason, limit)


def paraphrase_control(items: list[dict], threshold: float = MATCH_THRESHOLD) -> dict:
    """How many rewordings, and how many different claims, the matcher takes for the reviewed claim."""
    got = {"n": len(items), "reword_matched": 0, "different_matched": 0}
    for item in items:
        reviewed = [{"user": "u", "claim": item["reviewed"], "refs": [1]}]
        for kind in ("reword", "different"):
            got[f"{kind}_matched"] += bool(match([("u", item[kind], [1])], reviewed, threshold))
    return got
