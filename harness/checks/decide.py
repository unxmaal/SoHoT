"""Typed decisions over a flat schema: accuracy per field, plus calibration. #423."""
from __future__ import annotations

import json
import math
import re
import string

from harness.checks.base import CheckResult

CODES = string.ascii_uppercase
#: Equal-width bins over the top-choice probability, the convention nimble uses.
ECE_BINS = 10
#: Below this many pooled decisions a 10-bin ECE is mostly empty bins.
MIN_ECE_N = 100
TYPES = ("enum", "boolean")


class SchemaError(ValueError):
    pass


def choices(spec: dict) -> list:
    """The allowed answers of one field, in code order."""
    kind = spec.get("type")
    if kind == "boolean":
        got = spec.get("choices") or [False, True]
        if sorted(got) != [False, True]:
            raise SchemaError(f"boolean choices must be false and true, got {got!r}")
        return list(got)
    if kind == "enum":
        got = [str(c) for c in spec.get("choices") or []]
        if not 1 < len(got) <= len(CODES) or len(set(got)) != len(got):
            raise SchemaError(f"an enum needs 2-{len(CODES)} distinct choices, got {got!r}")
        return got
    raise SchemaError(f"field type must be one of {TYPES}, got {kind!r}")


def validate(schema: dict, answers: dict) -> None:
    """A schema every engine can take, and a gold answer for every field."""
    if not isinstance(schema, dict) or not schema:
        raise SchemaError("params.schema must map field names to fields")
    for name, spec in schema.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(name)):
            raise SchemaError(f"field name {name!r} must be snake_case")
        allowed = choices(spec)
        if not str(spec.get("description") or "").strip():
            raise SchemaError(f"field {name!r} needs a description")
        if name not in (answers or {}):
            raise SchemaError(f"field {name!r} has no gold answer in assert.answers")
        if key(answers[name]) not in {key(c) for c in allowed}:
            raise SchemaError(f"gold {answers[name]!r} for {name!r} is not one of {allowed!r}")
    extra = set(answers or {}) - set(schema)
    if extra:
        raise SchemaError(f"assert.answers names fields the schema lacks: {sorted(extra)}")


def key(value) -> str:
    """One spelling per answer: booleans as `true`/`false`, enums as written."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def code_map(spec: dict) -> dict[str, str]:
    """Letter code -> answer key, the same mapping nimble's scorer builds."""
    return {CODES[i]: key(c) for i, c in enumerate(choices(spec))}


def render(schema: dict) -> str:
    """The schema as the text models read: one block per field, lettered choices."""
    lines = []
    for name, spec in schema.items():
        lines.append(f"{name}: {spec['description'].strip()}")
        notes = spec.get("choice_descriptions") or {}
        for code, value in code_map(spec).items():
            note = notes.get(value) if isinstance(notes, dict) else None
            lines.append(f"  {code} = {value}" + (f": {note}" if note else ""))
    example = ", ".join(f'"{n}": "A"' for n in schema)
    return ("Answer every field below with the letter of exactly one of its "
            "choices.\n\n" + "\n".join(lines) + "\n\nReply with only a JSON "
            f"object mapping each field to its letter, like {{{example}}}.")


def _json_object(text: str) -> dict | None:
    text = (text or "").strip()
    fence = re.search(r"```[a-zA-Z]*\s*\n(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        got = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


_TRUE = {"true", "yes", "y"}
_FALSE = {"false", "no", "n"}


def _answer_key(raw, spec: dict) -> str | None:
    """A model's answer for one field as an answer key, or None if it is none."""
    codes = code_map(spec)
    allowed = set(codes.values())
    if isinstance(raw, bool):
        got = key(raw)
        return got if got in allowed else None
    text = str(raw if raw is not None else "").strip().strip('"').strip()
    if text.upper() in codes and (len(text) == 1):
        return codes[text.upper()]
    if text in allowed:
        return text
    low = text.lower()
    if spec.get("type") == "boolean":
        if low in _TRUE:
            return "true"
        if low in _FALSE:
            return "false"
    for value in allowed:
        if value.lower() == low:
            return value
    return None


def parse(artifact, schema: dict) -> dict[str, dict]:
    """field -> {"answer": key or None, "probs": {key: p} or None}.

    Accepts the canonical shape a runner with probabilities writes
    ({"answers": ..., "probabilities": ...}) or a model's bare {field: code}.
    """
    body = artifact if isinstance(artifact, dict) else _json_object(str(artifact or ""))
    body = body or {}
    answers = body.get("answers") if isinstance(body.get("answers"), dict) else body
    probs = body.get("probabilities") if isinstance(body.get("probabilities"), dict) else {}
    out = {}
    for name, spec in schema.items():
        answer = _answer_key(answers.get(name), spec) if name in answers else None
        dist = _distribution(probs.get(name), spec)
        if answer is None and dist:
            answer = max(dist, key=dist.get)
        out[name] = {"answer": answer, "probs": dist}
    return out


def _distribution(raw, spec: dict) -> dict[str, float] | None:
    """A probability per allowed answer, renormalised, or None if unusable."""
    if not isinstance(raw, dict) or not raw:
        return None
    allowed = list(code_map(spec).values())
    got = {a: 0.0 for a in allowed}
    for k, p in raw.items():
        name = _answer_key(k, spec)
        try:
            value = float(p)
        except (TypeError, ValueError):
            return None
        if name is None or not math.isfinite(value) or value < 0:
            continue
        got[name] += value
    total = sum(got.values())
    if total <= 0:
        return None
    return {a: v / total for a, v in got.items()}


def field_scores(parsed: dict, gold: dict, schema: dict) -> list[dict]:
    """Per field: correct, multiclass Brier in [0, 2], top probability, calibrated."""
    rows = []
    for name, spec in schema.items():
        allowed = list(code_map(spec).values())
        want = key(gold[name])
        got = parsed.get(name) or {}
        answer = got.get("answer")
        dist = got.get("probs")
        calibrated = dist is not None
        if dist is None:
            # One-hot on the answer; no answer at all is the zero vector.
            dist = {a: (1.0 if a == answer else 0.0) for a in allowed}
        brier = sum((dist.get(a, 0.0) - (1.0 if a == want else 0.0)) ** 2
                    for a in allowed)
        rows.append({"field": name, "answer": answer, "gold": want,
                     "correct": answer == want, "brier": brier,
                     "confidence": dist.get(answer, 0.0) if answer else 0.0,
                     "calibrated": calibrated})
    return rows


def ece(pairs, bins: int = ECE_BINS) -> float:
    """Expected calibration error over (confidence, correct) pairs."""
    pairs = [(float(c), bool(k)) for c, k in pairs]
    if not pairs:
        return 0.0
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [(c, k) for c, k in pairs
                  if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if inside:
            conf = sum(c for c, _ in inside) / len(inside)
            acc = sum(1 for _, k in inside if k) / len(inside)
            total += len(inside) / len(pairs) * abs(conf - acc)
    return total


def _letter(token) -> str:
    got = re.sub(r"[^A-Za-z0-9]", "", str(token or "").replace("Ġ", "").replace("▁", ""))
    return got if len(got) == 1 and got.isupper() else ""


def from_logprobs(text: str, tokens: list, schema: dict) -> dict:
    """The canonical artifact from a completion and its token logprobs.

    The k-th single-letter token after the last `{` is the k-th value in the
    JSON; a field whose letter does not line up keeps its answer, one-hot.
    """
    body = _json_object(text) or {}
    order = [n for n in body if n in schema]
    tokens = [t for t in (tokens or []) if isinstance(t, dict)]
    start = max((i for i, t in enumerate(tokens) if "{" in str(t.get("token", ""))),
                default=-1)
    letters = [t for t in tokens[start + 1:] if _letter(t.get("token"))]
    answers, probs = {}, {}
    for i, name in enumerate(order):
        spec = schema[name]
        answer = _answer_key(body[name], spec)
        if answer is None:
            continue
        answers[name] = answer
        if i >= len(letters):
            continue
        tok = letters[i]
        codes = code_map(spec)
        if codes.get(_letter(tok.get("token"))) != answer:
            continue
        seen = [e for e in tok.get("top_logprobs") or [] if isinstance(e, dict)]
        if not any(_letter(e.get("token")) == _letter(tok.get("token")) for e in seen):
            seen.append(tok)
        mass: dict[str, float] = {}
        for entry in seen:
            code = _letter(entry.get("token"))
            try:
                lp = float(entry.get("logprob"))
            except (TypeError, ValueError):
                continue
            if code in codes and math.isfinite(lp):
                mass[codes[code]] = mass.get(codes[code], 0.0) + math.exp(lp)
        if mass:
            probs[name] = mass
    return {"answers": answers, "probabilities": probs}


def check(artifact, schema: dict, gold: dict) -> CheckResult:
    """Pass when every field is answered correctly; the metrics carry the rest."""
    rows = field_scores(parse(artifact, schema), gold, schema)
    n = len(rows)
    right = sum(1 for r in rows if r["correct"])
    brier = sum(r["brier"] for r in rows)
    missing = [r["field"] for r in rows if r["answer"] is None]
    wrong = [f"{r['field']}={r['answer']} (gold {r['gold']})" for r in rows
             if r["answer"] is not None and not r["correct"]]
    out = CheckResult(ok=right == n)
    if missing:
        out.reason = f"no answer for {', '.join(missing)}"
        if wrong:
            out.reason += f"; wrong: {', '.join(wrong)}"
    elif wrong:
        out.reason = f"wrong: {', '.join(wrong)}"
    out.metrics = {
        "decide_accuracy": round(right / n, 4), "decide_correct": right,
        "decide_fields": n, "decide_brier": round(brier / n, 4),
        "decide_brier_sum": round(brier, 6),
        "calibrated": 1.0 if all(r["calibrated"] for r in rows) else 0.0,
        "decisions": [[round(r["confidence"], 6), int(r["correct"])] for r in rows],
    }
    return out
