"""Scoring marked personal data against labelled spans, by token. #564.

A token is a run of letters and digits; it is PII when it overlaps a labelled
span, and marked when it overlaps a predicted one. Label names are ignored:
the lane asks which text a filter would hide, and every model names its
classes differently.
"""
from __future__ import annotations

import json
import re

from harness.checks.base import CheckResult

#: A case passes at this token F1, or with nothing marked when nothing is personal.
PASS_F1 = 0.8
_TOKEN = re.compile(r"[A-Za-z0-9]+")


def _hits(start: int, end: int, spans) -> bool:
    return any(s < end and e > start for s, e in spans)


def counts(text: str, gold, predicted) -> tuple[int, int, int]:
    """(true positives, false positives, false negatives) over the text's tokens."""
    tp = fp = fn = 0
    for m in _TOKEN.finditer(text):
        g = _hits(m.start(), m.end(), gold)
        p = _hits(m.start(), m.end(), predicted)
        tp += g and p
        fp += p and not g
        fn += g and not p
    return tp, fp, fn


def parse(answer: str) -> list[tuple[int, int]]:
    """[(start, end)] from {"spans": [[s, e, label?] | {"start", "end"}]}; ValueError otherwise."""
    got = json.loads(answer)
    spans = got.get("spans") if isinstance(got, dict) else got
    if not isinstance(spans, list):
        raise ValueError("no spans list in the output")
    out = []
    for s in spans:
        if isinstance(s, dict):
            out.append((int(s["start"]), int(s["end"])))
        else:
            out.append((int(s[0]), int(s[1])))
    return out


def check(answer: str, text: str, gold) -> CheckResult:
    try:
        predicted = parse(answer)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return CheckResult(False, f"no spans could be read: {exc}")
    tp, fp, fn = counts(text, gold, predicted)
    den = 2 * tp + fp + fn
    f1 = 2 * tp / den if den else 1.0
    ok = (fp == 0) if not (tp + fn) else f1 >= PASS_F1
    out = CheckResult(ok, "")
    out.metrics = {"pii_f1": round(f1, 4), "pii_2tp": 2 * tp, "pii_f1_den": den,
                   "pii_precision": round(tp / (tp + fp), 4) if tp + fp else float(not (tp + fn)),
                   "pii_recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
                   "pii_tp": tp, "pii_pred": tp + fp, "pii_gold": tp + fn}
    if not ok:
        missed = [text[s:e] for s, e in gold if not _hits(s, e, predicted)]
        out.reason = (f"token F1 {f1:.2f}: {fp} token(s) marked that are not personal, "
                      f"{fn} personal token(s) left; missed {missed}")
    return out
