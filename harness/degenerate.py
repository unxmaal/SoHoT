"""Whether a reply cut at the token budget was looping or collapsed, not cut mid-answer (#955)."""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

#: Characters at the end of the visible reply the measure reads.
TAIL_CHARS = 4000
#: A shorter visible reply is a budget spent on reasoning, never measured.
MIN_CHARS = 512
#: A character counts as repeated when it sits in a span this long seen earlier in the tail.
SPAN = 64
#: Fitted on evals/degenerate/rows.jsonl by fit(); refit when a row lands inside the margin.
REPEAT_SHARE = 0.677
ENTROPY_BITS = 3.412
#: The lanes the threshold was fitted on; elsewhere every cut reply stays a limit.
LANES = ("code",)
#: The labelled rows: hand labels for budget-cut replies and passing replies as the negative control.
ROWS = Path(__file__).resolve().parents[1] / "evals" / "degenerate" / "rows.jsonl"
DEGENERATE, CUT_OFF, NATURAL = "degenerate", "cut_off", "natural"


def repeat_share(tail: str, span: int = SPAN) -> float:
    """Share of `tail` inside a `span`-character substring that already occurred earlier in it."""
    if len(tail) < span:
        return 0.0
    seen: set = set()
    covered = bytearray(len(tail))
    for i in range(len(tail) - span + 1):
        piece = tail[i:i + span]
        if piece in seen:
            covered[i:i + span] = b"\x01" * span
        else:
            seen.add(piece)
    return sum(covered) / len(tail)


def entropy_bits(tail: str) -> float:
    """Shannon entropy per character of `tail` with whitespace removed; 0.0 when nothing is left."""
    chars = [c for c in tail if not c.isspace()]
    if not chars:
        return 0.0
    n = len(chars)
    return max(0.0, -sum(k / n * math.log2(k / n) for k in Counter(chars).values()))


def measure(text: str) -> dict:
    """{"tail_repeat", "tail_entropy"} over the reply's tail; {} when the visible reply is under MIN_CHARS."""
    text = text or ""
    if len(text) > TAIL_CHARS:
        from harness import cuts
        cuts.cut("degenerate_tail_chars", "budget-cut reply measured on its tail only",
                 kept=TAIL_CHARS, dropped=len(text) - TAIL_CHARS)
    tail = text[-TAIL_CHARS:]
    if len(tail) < MIN_CHARS:
        return {}
    return {"tail_repeat": round(repeat_share(tail), 4), "tail_entropy": round(entropy_bits(tail), 4)}


def is_degenerate(got: dict, repeat: float = REPEAT_SHARE, entropy: float = ENTROPY_BITS) -> bool:
    if not got:
        return False
    return got["tail_repeat"] >= repeat or got["tail_entropy"] <= entropy


def load(path: Path = ROWS) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def fit(rows: list[dict]) -> dict:
    """Both thresholds as midpoints: repeat between non-degenerate rows and loops, entropy for the degenerate rest."""
    scored = [(r["label"], measure(r["tail"])) for r in rows]
    other = [m for label, m in scored if label != DEGENERATE and m]
    bad = [m for label, m in scored if label == DEGENERATE]
    if not other or not bad or not all(bad):
        raise ValueError("fit needs measured rows of both classes, and every degenerate row over MIN_CHARS")
    top = max(m["tail_repeat"] for m in other)
    loops = [m for m in bad if m["tail_repeat"] > top]
    if not loops:
        raise ValueError("no degenerate row repeats more than every non-degenerate row")
    floor = min(m["tail_repeat"] for m in loops)
    repeat = (top + floor) / 2
    rest = [m for m in bad if m["tail_repeat"] < repeat]
    low = min(m["tail_entropy"] for m in other)
    high = max((m["tail_entropy"] for m in rest), default=0.0)
    if rest and high >= low:
        raise ValueError(f"entropy cannot split the rows repetition misses: {high:.3f} >= {low:.3f}")
    entropy = (low + high) / 2 if rest else low / 2
    return {"repeat": round(repeat, 4), "repeat_margin": round((floor - top) / 2, 4),
            "repeat_range": {"other_max": top, "degenerate_min": floor},
            "entropy": round(entropy, 4), "entropy_margin": round((low - high) / 2, 4),
            "entropy_range": {"other_min": low, "degenerate_max": high},
            "counts": dict(Counter(label for label, _ in scored))}


def agreement(rows: list[dict], repeat: float = REPEAT_SHARE, entropy: float = ENTROPY_BITS) -> list[dict]:
    """The labelled rows the classifier disagrees with at these thresholds."""
    wrong = []
    for r in rows:
        got = is_degenerate(measure(r["tail"]), repeat, entropy)
        if got != (r["label"] == DEGENERATE):
            wrong.append({k: r.get(k) for k in ("run", "candidate", "case_id", "label")})
    return wrong


def inside_margin(got: dict, fitted: dict) -> bool:
    """Whether a measured row sits between the two classes either threshold was fitted across."""
    if not got:
        return False
    rr, er = fitted["repeat_range"], fitted["entropy_range"]
    return (rr["other_max"] < got["tail_repeat"] < rr["degenerate_min"]
            or er["degenerate_max"] < got["tail_entropy"] < er["other_min"])
