"""Rubric evaluation by a local model, scored against a person's labels. #286.

An eval set is a directory: rubric.yaml, items.jsonl ({id, text} per line) and
labels.jsonl, which only the labelling page appends to. It lives under
$LOCALHARNESS_HOME, never in the repo, because the items are other people's
words.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx
import jsonschema
import yaml

from harness import gateway_key

CANT_TELL = "cant-tell"
TEMPERATURE = 0
#: Bump when the labelling page changes what a person sees. RULE #309.
INTERFACE = 1


@dataclass(frozen=True)
class Rubric:
    name: str
    version: int
    instructions: str
    schema: dict
    label: str

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self.schema["properties"][self.label]["enum"])

    @property
    def stamp(self) -> str:
        blob = json.dumps([self.instructions, self.schema, self.label],
                          sort_keys=True).encode("utf-8")
        return f"{self.name}@{self.version}#{hashlib.sha256(blob).hexdigest()[:8]}"


@dataclass
class EvalSet:
    root: Path
    rubric: Rubric
    items: list[dict]

    def item(self, item_id: str) -> dict:
        for i in self.items:
            if i["id"] == item_id:
                return i
        raise KeyError(item_id)


@dataclass
class Verdict:
    ok: bool
    label: str | None
    raw: str
    error: str
    seconds: float


def _rubric(path: Path) -> Rubric:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    r = Rubric(d["name"], int(d["version"]), d["instructions"], d["schema"],
               d["label"])
    field = r.schema.get("properties", {}).get(r.label, {})
    if not field.get("enum"):
        raise ValueError(f"{path}: label field {r.label!r} needs an enum")
    if r.label not in r.schema.get("required", []):
        raise ValueError(f"{path}: label field {r.label!r} must be required")
    jsonschema.Draft202012Validator.check_schema(r.schema)
    return r


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def load_set(root) -> EvalSet:
    root = Path(root)
    items = _jsonl(root / "items.jsonl")
    seen = Counter(i["id"] for i in items)
    dupes = [k for k, n in seen.items() if n > 1]
    if dupes:
        raise ValueError(f"duplicate item ids: {dupes[:5]}")
    return EvalSet(root, _rubric(root / "rubric.yaml"), items)


def record_label(root, item_id: str, label: str, repeat: bool = False) -> None:
    s = load_set(root)
    s.item(item_id)
    if label not in s.rubric.labels + (CANT_TELL,):
        raise ValueError(f"{label!r} is not one of {s.rubric.labels}")
    row = {"id": item_id, "label": label, "repeat": repeat,
           "rubric": s.rubric.stamp, "interface": INTERFACE, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(Path(root) / "labels.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def labels(root) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in _jsonl(Path(root) / "labels.jsonl"):
        out.setdefault(row["id"], []).append(row["label"])
    return out


def gold(root) -> dict[str, str]:
    """Majority of the decided labels; a tie or only `cant-tell` is no gold."""
    out = {}
    for item_id, got in labels(root).items():
        counts = Counter(x for x in got if x != CANT_TELL).most_common()
        if counts and (len(counts) == 1 or counts[0][1] > counts[1][1]):
            out[item_id] = counts[0][0]
    return out


def self_agreement(root) -> tuple[int, int]:
    """(repeats matching the first answer, repeats)."""
    agree = total = 0
    for got in labels(root).values():
        for later in got[1:]:
            total += 1
            agree += later == got[0]
    return agree, total


def next_item(root, rng, repeat_rate: float = 0.1):
    """(item, is_repeat), or None when nothing is left to label."""
    s = load_set(root)
    done = labels(root)
    once = [i for i in s.items if len(done.get(i["id"], [])) == 1]
    if once and rng.random() < repeat_rate:
        return rng.choice(once), True
    fresh = [i for i in s.items if i["id"] not in done]
    if fresh:
        return fresh[0], False
    return None


def request(rubric: Rubric, text: str, model: str) -> dict:
    """Rubric first and identical every call, so the server's prefix cache
    holds it; only the item changes. RULE #326."""
    return {"model": model, "temperature": TEMPERATURE, "max_tokens": 600,
            "messages": [{"role": "system", "content": rubric.instructions},
                         {"role": "user", "content": text}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": rubric.name, "strict": True, "schema": rubric.schema}}}


def evaluate(rubric: Rubric, text: str, model: str, gateway: str,
             post=httpx.post, timeout: float = 300.0) -> Verdict:
    t0 = time.monotonic()
    raw = ""
    try:
        r = post(f"{gateway.rstrip('/')}/v1/chat/completions",
                 json=request(rubric, text, model), timeout=timeout,
                 headers=gateway_key.headers())
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"].get("content") or ""
        value = json.loads(raw)
        jsonschema.validate(value, rubric.schema)
        return Verdict(True, value[rubric.label], raw, "",
                       time.monotonic() - t0)
    except httpx.HTTPStatusError as exc:
        why = f"{type(exc).__name__}: {exc}"[:300]
        if gateway_key.refused(exc.response.status_code, exc.response.text, gateway_key.key()):
            why = f"gateway refused the key: {gateway_key.HINT}"
        return Verdict(False, None, raw, why, time.monotonic() - t0)
    except (ValueError, KeyError, IndexError, TypeError,
            jsonschema.ValidationError, httpx.HTTPError) as exc:
        return Verdict(False, None, raw, f"{type(exc).__name__}: {exc}"[:300],
                       time.monotonic() - t0)


def run(evalset: EvalSet, candidates, gateway: str, post=httpx.post) -> dict:
    gold_labels = gold(evalset.root)
    if not gold_labels:
        raise ValueError("no item has a decided label yet; label some first")
    floor = Counter(gold_labels.values()).most_common(1)[0][1] / len(gold_labels)
    report = {"rubric": evalset.rubric.stamp, "temperature": TEMPERATURE,
              "gateway": gateway, "floor": floor,
              "ceiling": self_agreement(evalset.root),
              "labels_digest": hashlib.sha256(
                  json.dumps(sorted(gold_labels.items())).encode("utf-8")
              ).hexdigest()[:8],
              "candidates": {}, "rows": []}
    for model in candidates:
        times, valid, agree = [], 0, 0
        for item_id, want in sorted(gold_labels.items()):
            v = evaluate(evalset.rubric, evalset.item(item_id)["text"], model,
                         gateway, post=post)
            times.append(v.seconds)
            valid += v.ok
            agree += v.ok and v.label == want
            report["rows"].append({"candidate": model, "id": item_id,
                                   "gold": want, "label": v.label, "ok": v.ok,
                                   "raw": v.raw, "error": v.error,
                                   "seconds": round(v.seconds, 3)})
        n = len(gold_labels)
        report["candidates"][model] = {
            "n": n, "valid": valid, "agree": agree, "agreement": agree / n,
            "beats_floor": agree / n > floor,
            "median_s": round(statistics.median(times), 3)}
    return report
