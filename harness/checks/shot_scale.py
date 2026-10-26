"""Shot scale of a film frame against a human label: linearly weighted kappa, gated by a shuffled-label control. #1207."""
from __future__ import annotations

import random
import re

#: CineScale's ordinal scales, closest first; FS (foreground) and INS (insert) are not on the ladder.
LADDER = ("ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS")
#: CineScale's shotscale column: code -> label, as its README maps them.
CINESCALE = ("FS", "ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS", "INS", "NA")
INVALID = "invalid"
#: Spellings a reply may use for each scale; anything else is invalid.
ALIASES = {
    "ECU": ("ecu", "extreme close up", "extreme closeup"),
    "CU": ("cu", "close up", "closeup"),
    "MCU": ("mcu", "medium close up", "medium closeup"),
    "MS": ("ms", "medium shot"),
    "MLS": ("mls", "medium long shot"),
    "LS": ("ls", "long shot"),
    "ELS": ("els", "extreme long shot"),
}
_BY_ALIAS = {a: label for label, names in ALIASES.items() for a in names}
_FIND = re.compile(r"(?<![a-z0-9])(" + "|".join(sorted(map(re.escape, _BY_ALIAS), key=len, reverse=True))
                   + r")(?![a-z0-9])")

PROMPT = ("What is the shot scale of this film frame? Answer with exactly one code: "
          "ECU (extreme close-up: part of a face), CU (close-up: a face), "
          "MCU (medium close-up: head and shoulders), MS (medium shot: from the waist up), "
          "MLS (medium long shot: from the knees up), LS (long shot: the whole body), "
          "ELS (extreme long shot: people small in a wide view).")

#: Seeded permutations of the true labels each run's control scores.
CONTROL_DRAWS = 20
#: Largest |mean kappa| a control may reach before the run is discarded.
CONTROL_MAX_KAPPA = 0.1


def parse(reply: str) -> str:
    """The one scale a reply names, or INVALID when it names none or two."""
    text = re.sub(r"\s+", " ", re.sub(r"[-_]", " ", str(reply or "").lower()))
    found = {_BY_ALIAS[m] for m in _FIND.findall(text)}
    return found.pop() if len(found) == 1 else INVALID


def step(label: str, k: int) -> str:
    """The scale k steps wider (k > 0) or closer, held at the ends of the ladder."""
    i = min(max(LADDER.index(label) + k, 0), len(LADDER) - 1)
    return LADDER[i]


def _weight(t: str, a: str) -> float:
    if a not in LADDER:
        return 1.0
    return abs(LADDER.index(t) - LADDER.index(a)) / (len(LADDER) - 1)


def kappa(truth, answers) -> float | None:
    """Linearly weighted Cohen's kappa; an invalid answer is its own column at the widest disagreement."""
    pairs = [(t, a if a in LADDER else INVALID) for t, a in zip(truth, answers) if t in LADDER]
    n = len(pairs)
    if not n:
        return None
    rows: dict[str, int] = {}
    cols: dict[str, int] = {}
    observed = 0.0
    for t, a in pairs:
        rows[t] = rows.get(t, 0) + 1
        cols[a] = cols.get(a, 0) + 1
        observed += _weight(t, a)
    expected = sum(r * c * _weight(t, a) for t, r in rows.items() for a, c in cols.items()) / n
    if expected == 0:
        return None
    return 1.0 - observed / expected


def _part(rows) -> dict:
    truth = [r["truth"] for r in rows]
    answers = [r["answer"] for r in rows]
    n = len(rows)
    near = sum(1 for t, a in zip(truth, answers) if a in LADDER and abs(LADDER.index(t) - LADDER.index(a)) <= 1)
    top = max((truth.count(t) for t in set(truth)), default=0)
    return {"n": n, "kappa": kappa(truth, answers),
            "accuracy": sum(t == a for t, a in zip(truth, answers)) / n if n else None,
            "within_one": near / n if n else None,
            "majority": top / n if n else None,
            "valid_rate": sum(a in LADDER for a in answers) / n if n else None}


def score(rows) -> dict:
    """Pooled and per-film figures over rows of {film, id, truth, answer}."""
    out = _part(rows)
    confusion: dict[str, dict[str, int]] = {}
    for r in rows:
        cell = confusion.setdefault(r["truth"], {})
        cell[r["answer"]] = cell.get(r["answer"], 0) + 1
    out["confusion"] = confusion
    out["films"] = {f: _part([r for r in rows if r["film"] == f]) for f in sorted({r["film"] for r in rows})}
    return out


def shuffled(truth, rng) -> list:
    out = list(truth)
    rng.shuffle(out)
    return out


def control(rows, draws: int | None = None, seed: int = 1207, permute=shuffled) -> dict:
    """Kappa of the answers against the true labels permuted within each film, over seeded draws."""
    draws = CONTROL_DRAWS if draws is None else draws
    rng = random.Random(seed)
    films = sorted({r["film"] for r in rows})
    values = []
    for _ in range(draws):
        truth, answers = [], []
        for f in films:
            mine = [r for r in rows if r["film"] == f]
            truth += permute([r["truth"] for r in mine], rng)
            answers += [r["answer"] for r in mine]
        k = kappa(truth, answers)
        values.append(0.0 if k is None else k)
    mean = sum(values) / len(values) if values else 0.0
    return {"draws": draws, "mean": mean, "max_abs": max((abs(v) for v in values), default=0.0)}


HEADLINE = ("kappa", "accuracy", "within_one", "films", "confusion")


def judge(rows, draws: int | None = None, max_kappa: float | None = None, seed: int = 1207,
          permute=shuffled, extra_control=None) -> dict:
    """score() plus its control; a control over the bar discards the run and withholds its kappa."""
    max_kappa = CONTROL_MAX_KAPPA if max_kappa is None else max_kappa
    out = score(rows)
    out["control"] = control(rows, draws, seed, permute)
    out["status"], out["reason"] = "ok", ""
    if abs(out["control"]["mean"]) > max_kappa:
        out["status"] = "discarded"
        out["reason"] = (f"control: kappa {out['control']['mean']:.3f} against shuffled labels "
                         f"exceeds {max_kappa}")
    elif extra_control:
        mean = sum(extra_control) / len(extra_control)
        if abs(mean) > max_kappa:
            out["status"] = "discarded"
            out["reason"] = f"control: a probe trained on shuffled labels scores kappa {mean:.3f}, over {max_kappa}"
    if out["status"] != "ok":
        for k in HEADLINE:
            out.pop(k, None)
    return out


def paired_kappa(truth, a, b, films, draws: int, level: float, seed: int = 1282) -> dict:
    """Two answer lists on the same frames: kappa difference, a bootstrap interval resampling frames within each film, agreement. #1282."""
    n = len(truth)
    ka, kb = kappa(truth, a) or 0.0, kappa(truth, b) or 0.0
    by_film: dict[str, list[int]] = {}
    for i, f in enumerate(films):
        by_film.setdefault(f, []).append(i)
    rng = random.Random(seed)
    diffs = []
    for _ in range(draws):
        pick = [rng.choice(idx) for idx in by_film.values() for _ in idx]
        t = [truth[i] for i in pick]
        diffs.append((kappa(t, [a[i] for i in pick]) or 0.0) - (kappa(t, [b[i] for i in pick]) or 0.0))
    diffs.sort()
    lo = diffs[int((1 - level) / 2 * (draws - 1))]
    hi = diffs[int((1 + level) / 2 * (draws - 1))]
    return {"kappa_a": ka, "kappa_b": kb, "diff": ka - kb, "low": lo, "high": hi, "level": level, "draws": draws,
            "agree": sum(x == y for x, y in zip(a, b)) / n if n else 0.0, "n": n, "films": len(by_film)}
