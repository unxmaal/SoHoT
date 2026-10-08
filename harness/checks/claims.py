"""Claims lane scoring: schema validation, then emitted claims matched to human-reviewed ones. #654.

A reason never quotes case or reply text: claims cases are private and reasons reach the store.
"""
from __future__ import annotations

import json
import math
import re
import statistics
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
#: Bumped whenever matching changes, since every stored claims score moves with it: 2 is IDF-weighted. #662.
MATCHER_VERSION = 2
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
_STOPWORDS = frozenset(
    "a an and are as at be been by did do does for from has have in into is it its of on or rather than that "
    "the their there these this those to was were which with".split())
#: Who said it, not what was said: reported-speech framing a claim may or may not carry. #662.
_FRAMING = frozenset(
    "i me my mine we our us you your they them he him his she her member members user users "
    "say says said mention mentions mentioned note notes noted state states stated report reports "
    "reported".split())
_NUMBERS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split(), map(str, range(21))))
_NEGATIONS = {"lacks": ("not",), "lack": ("not",), "no": ("not",), "t": (),
              **{w: ("not",) for w in "aren didn doesn don hasn haven isn wasn weren won".split()}}
#: An anonymised handle's suffix, as in member-a1b2: four hex digits holding a letter and a digit.
_HANDLE = re.compile(r"(?=[0-9a-f]*[a-f])(?=[a-f]*[0-9])[0-9a-f]{4}")
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


def dice(a: str, b: str) -> float:
    """Dice coefficient over raw word multisets, in [0, 1]: matcher version 1, kept as the control's foil."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 0.0
    common = sum((Counter(ta) & Counter(tb)).values())
    return 2 * common / (len(ta) + len(tb))


def _stem(t: str) -> str:
    if any(c.isdigit() for c in t):
        return t
    for suffix in ("ing", "ed", "es", "s"):
        if t.endswith(suffix) and not t.endswith("ss") and len(t) - len(suffix) >= 3:
            t = t[:-len(suffix)]
            break
    return t[:-1] if t.endswith("e") and len(t) > 3 else t


def content_tokens(text: str) -> list[str]:
    """Lowercased content words: stopwords, framing and handles dropped, numbers and negations spelled one way, stemmed."""
    out = []
    for t in _tokens(text):
        t = _NUMBERS.get(t, t)
        if t in _NEGATIONS:
            out.extend(_NEGATIONS[t])
        elif t not in _STOPWORDS and t not in _FRAMING and not _HANDLE.fullmatch(t):
            out.append(_stem(t))
    return out


def weights(corpus) -> "callable":
    """Smoothed IDF over a case's distinct reviewed claims: a word in all of them (the subject) weighs least."""
    docs = [set(content_tokens(c)) for c in dict.fromkeys(corpus)]
    df = Counter(t for d in docs for t in d)
    n = len(docs)
    # A word no reviewed claim uses weighs as the rarest one does, so framing a reviewer never saw cannot sink a match.
    return lambda t: math.log(1 + n / max(df.get(t, 0), 1))


def similarity(a: str, b: str, weight=None) -> float:
    """Dice over content words, each counted at its weight, in [0, 1]; uniform weight when none is given."""
    weight = weight or (lambda t: 1.0)
    ca, cb = Counter(content_tokens(a)), Counter(content_tokens(b))
    total = sum(weight(t) * n for t, n in (ca + cb).items())
    if not total:
        return 0.0
    return 2 * sum(weight(t) * n for t, n in (ca & cb).items()) / total


def match(emitted: list, reviewed: list[dict], threshold: float, sim=None) -> list[tuple[int, int, float]]:
    """One-to-one (emitted index, reviewed index, similarity): same user, refs overlap, best first."""
    if sim is None:
        w = weights([r["claim"] for r in reviewed])
        sim = lambda a, b: similarity(a, b, w)
    pairs = []
    for i, (user, claim, refs) in enumerate(emitted):
        for j, r in enumerate(reviewed):
            if user != r["user"] or not set(refs) & set(r["refs"]):
                continue
            sim_ij = sim(claim, r["claim"])
            if sim_ij >= threshold:
                pairs.append((sim_ij, i, j))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    used_i, used_j, out = set(), set(), []
    for sim, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        out.append((i, j, sim))
    return sorted(out)


def _near_misses(emitted: list, reviews: list[dict], pairs: list, weight) -> int:
    """How many unmatched good reviews an unmatched claim missed by the threshold alone."""
    used_i, used_j = {i for i, _, _ in pairs}, {j for _, j, _ in pairs}
    floor = MATCH_THRESHOLD - _NEAR_MISS
    return sum(1 for j, r in enumerate(reviews)
               if j not in used_j and r["verdict"] == "good"
               and any(i not in used_i and user == r["user"] and set(refs) & set(r["refs"])
                       and similarity(claim, r["claim"], weight) >= floor
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
        out.metrics = {"claims_schema_valid": 0, "claims_judge_calibrated": 0,
                       "claims_matcher_version": MATCHER_VERSION}
        return out
    if expect_empty:
        kept = int(not emitted)
        out = CheckResult(bool(kept), "" if kept else f"expected no claims, emitted {len(emitted)}")
        out.metrics = {"claims_schema_valid": 1, "claims_emitted": len(emitted),
                       "claims_empty_kept": kept, "claims_empty_cases": 1,
                       "claims_empty_rate": float(kept), "claims_judge_calibrated": 0,
                       "claims_matcher_version": MATCHER_VERSION}
        return out
    metrics = {"claims_schema_valid": 1, "claims_emitted": len(emitted), "claims_judge_calibrated": 0,
               "claims_matcher_version": MATCHER_VERSION}
    # Word weights come from every review of the case, so each interface is scored by one similarity.
    weight = weights([r["claim"] for r in reviews])
    reason = limit = ""
    by: dict[str, list[dict]] = {}
    for r in reviews:
        by.setdefault(interface_of(r), []).append(r)
    for interface in sorted(by):
        mine, why, knob = _score(emitted, by[interface], weight)
        metrics.update({metric(k, interface): v for k, v in mine.items()})
        if why and not reason:
            reason, limit = f"{interface}: {why}", knob
    out = CheckResult(not reason, reason, limit=limit)
    out.metrics = metrics
    return out


def _score(emitted: list, reviews: list[dict], weight) -> tuple[dict, str, str]:
    """One interface's metrics, failure reason and deciding knob."""
    pairs = match(emitted, reviews, MATCH_THRESHOLD, sim=lambda a, b: similarity(a, b, weight))
    verdicts = Counter(reviews[j]["verdict"] for _, j, _ in pairs)
    good_total = sum(1 for r in reviews if r["verdict"] == "good")
    good = verdicts["good"]
    bad = sum(verdicts[v] for v in NEGATIVE)
    # A case whose reviews hold no good claim is passed by avoiding the rejected ones.
    recall = good / good_total if good_total else 1.0
    near = _near_misses(emitted, reviews, pairs, weight)
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


def paraphrase_control(items: list[dict], threshold: float = MATCH_THRESHOLD, plain: bool = False) -> dict:
    """Rewordings and different claims matched, with gap (lowest reword less highest different) and spread (larger class SD).

    Items sharing a `case` form one case whose reviewed claims weight the words; `plain` scores with version 1's Dice.
    """
    by_case: dict[str, list[str]] = {}
    for item in items:
        by_case.setdefault(str(item.get("case", "")), []).append(item["reviewed"])
    got = {"n": len(items), "reword_matched": 0, "different_matched": 0}
    scores: dict[str, list[float]] = {"reword": [], "different": []}
    for item in items:
        w = weights(by_case[str(item.get("case", ""))])
        sim = dice if plain else (lambda a, b, w=w: similarity(a, b, w))
        reviewed = [{"user": "u", "claim": item["reviewed"], "refs": [1]}]
        for kind in ("reword", "different"):
            got[f"{kind}_matched"] += bool(match([("u", item[kind], [1])], reviewed, threshold, sim=sim))
            scores[kind].append(sim(item[kind], item["reviewed"]))
    got["reword_min"] = round(min(scores["reword"]), 4)
    got["different_max"] = round(max(scores["different"]), 4)
    got["gap"] = round(got["reword_min"] - got["different_max"], 4)
    got["spread"] = round(max(statistics.pstdev(v) for v in scores.values()), 4)
    return got
