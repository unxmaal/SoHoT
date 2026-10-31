"""Local model labels, Claude checks a sample: batch decide and its scoring. #683."""
from __future__ import annotations

import json
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BANDS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 0.95), (0.95, 0.99), (0.99, 1.0)]


def key(value) -> str:
    """A choice as the string a probability is keyed by."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def family(id_: str) -> str:
    """A case id without its last part: check-squad2-56de -> check-squad2."""
    return id_.rsplit("-", 1)[0]


def read_items(path) -> list[dict]:
    """Items from JSONL or a JSON array; a line that does not parse is kept as a bad item."""
    text = Path(path).read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        return json.loads(text)
    items = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            items.append({"_bad": f"line {n}: {exc}"})
    return items


def read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def latest(rows) -> dict:
    """The last row per id; an answered row is never replaced by a later error."""
    out: dict = {}
    for r in rows:
        rid = r.get("id")
        if rid is None:
            continue
        if rid in out and not out[rid].get("error") and r.get("error"):
            continue
        out[rid] = r
    return out


def _probs(body: dict) -> dict:
    return {f: {key(c): float(p) for c, p in dist.items()}
            for f, dist in body["probabilities"].items()}


def run_batch(items, out, decide=None, concurrency: int = 4) -> dict:
    """Decide every item not already answered in `out`, one line each, errors included."""
    if decide is None:
        from harness import delegate
        decide = delegate.decide
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {i for i, r in latest(read_jsonl(out)).items() if not r.get("error")}
    lock = threading.Lock()
    counts = {"done": 0, "skipped": 0, "errors": 0}

    def write(row: dict) -> None:
        with lock, out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            counts["errors" if row["error"] else "done"] += 1

    def fail(rid: str, msg: str) -> None:
        write({"id": rid, "answers": {}, "probs": {}, "error": msg})

    def one(rid: str, item: dict) -> None:
        try:
            body = decide(item.get("question") or "", item["schema"],
                          context=item.get("context") or "")
            write({"id": rid, "answers": body["answers"], "probs": _probs(body),
                   "error": None})
        except Exception as exc:  # every failure is a line, never a silent drop
            fail(rid, str(exc) or type(exc).__name__)

    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
        for n, item in enumerate(items, 1):
            item = item if isinstance(item, dict) else {"_bad": f"line {n}: not an object"}
            rid = str(item.get("id") or f"line:{n}")
            if rid in done:
                counts["skipped"] += 1
                continue
            if item.get("_bad"):
                fail(rid, item["_bad"])
            elif not item.get("id"):
                fail(rid, "no id")
            elif not isinstance(item.get("schema"), dict) or not item["schema"]:
                fail(rid, "schema must be a non-empty object")
            else:
                pool.submit(one, rid, item)
    answered = {i for i, r in latest(read_jsonl(out)).items() if not r.get("error")}
    ids = [str(it.get("id") or f"line:{n}") if isinstance(it, dict) else f"line:{n}"
           for n, it in enumerate(items, 1)]
    counts["missing"] = [i for i in ids if i not in answered]
    return counts


def select(items, labels, threshold: float = 0.9, thresholds=None, every: int = 0) -> list[dict]:
    """Items to check blind: fields below their threshold, and every Nth item whole."""
    lab, thresholds = latest(labels), thresholds or {}
    todo, sure = [], 0
    for n, item in enumerate(items):
        row = lab.get(item.get("id")) if isinstance(item, dict) else None
        if not row or row.get("error"):
            continue
        schema = item.get("schema") or {}
        whole = every and n % every == 0
        keep = [f for f in schema if whole or (conf(row, f) is None or
                conf(row, f) < thresholds.get(f, threshold))]
        sure += len(schema) - len(keep)
        if keep:
            todo.append({"id": item["id"], "question": item.get("question") or "",
                         "context": item.get("context") or "",
                         "schema": {f: schema[f] for f in keep}})
    if sure:
        from harness import cuts
        cuts.cut("harness/label.py:select(threshold)", "fields left out of the blind check as confident",
                 value=threshold, dropped=sure)
    return todo


def conf(row: dict, field: str):
    try:
        return float(row["probs"][field][key(row["answers"][field])])
    except (KeyError, TypeError, ValueError):
        return None


def threshold(rows, target: float):
    """The lowest confidence t at which local accuracy over fields with conf >= t reaches target."""
    for t in sorted({c for c, _ in rows}):
        tail = [ok for c, ok in rows if c >= t]
        if sum(tail) / len(tail) >= target:
            return t
    return None


def _band(c: float) -> str | None:
    for lo, hi in BANDS:
        if lo <= c < hi or (hi == 1.0 and c == 1.0):
            return f"{lo:.2f}-{hi:.2f}"
    return None


def _acc(n: int, right: int) -> dict:
    return {"n": n, "right": right, "acc": round(right / n, 4) if n else None}


class _Tally:
    def __init__(self):
        self.n = self.right = 0

    def add(self, ok: bool) -> None:
        self.n += 1
        self.right += bool(ok)

    def out(self) -> dict:
        return _acc(self.n, self.right)


def score(labels, checks=(), gold=None, target: float = 0.95) -> dict:
    """Local accuracy by field, family and confidence; agreement with Claude; thresholds."""
    lab, chk = latest(labels), latest(checks or [])
    gold = gold or None
    local, final, claude = _Tally(), _Tally(), _Tally()
    by_field, by_family = defaultdict(_Tally), defaultdict(_Tally)
    by_band = {f"{lo:.2f}-{hi:.2f}": _Tally() for lo, hi in BANDS}
    tails: dict = defaultdict(list)
    agree = {"checked": 0, "agree": 0, "disagree": 0}
    if gold:
        agree.update(claude_right=0, local_right=0, neither=0)
    labelled = {i: r for i, r in lab.items() if not r.get("error")}
    for rid, row in labelled.items():
        checked = (chk.get(rid) or {}).get("answers") or {}
        for field, mine in (row.get("answers") or {}).items():
            tails.setdefault(field, [])
            theirs = checked.get(field)
            truth = (gold.get(rid) or {}).get(field) if gold else theirs
            if field in checked:
                agree["checked"] += 1
                same = key(mine) == key(theirs)
                agree["agree" if same else "disagree"] += 1
                if gold and truth is not None:
                    claude.add(key(theirs) == key(truth))
                    if not same:
                        who = ("claude_right" if key(theirs) == key(truth) else
                               "local_right" if key(mine) == key(truth) else "neither")
                        agree[who] += 1
            if truth is None:
                continue
            ok = key(mine) == key(truth)
            local.add(ok)
            by_field[field].add(ok)
            by_family[family(rid)].add(ok)
            used = theirs if (gold and field in checked) else mine
            final.add(key(used) == key(truth))
            c = conf(row, field)
            if c is not None:
                by_band[_band(c)].add(ok)
                tails[field].append((c, ok))
    return {
        "items": len(lab), "labelled": len(labelled), "errors": len(lab) - len(labelled),
        "reference": "gold" if gold else "claude", "target": target,
        "local": local.out(), "final": final.out(), "claude": claude.out(),
        "by_field": {f: t.out() for f, t in sorted(by_field.items())},
        "by_family": {f: t.out() for f, t in sorted(by_family.items())},
        "by_band": [{"band": b, **t.out()} for b, t in by_band.items()],
        "agreement": agree,
        "thresholds": {f: threshold(rows, target) for f, rows in sorted(tails.items())},
    }


def _line(name: str, a: dict) -> str:
    acc = "-" if a["acc"] is None else f"{a['acc']:.3f}"
    return f"  {name:<24} {a['right']:>5}/{a['n']:<5} {acc}"


def render(s: dict) -> str:
    """The score as plain text."""
    out = ["coverage",
           f"  items {s['items']}  labelled {s['labelled']}  errors {s['errors']}  "
           f"reference {s['reference']}",
           _line("local", s["local"]), _line("claude (checked)", s["claude"]),
           _line("final (claude on checked)", s["final"]), "by field"]
    out += [_line(f, a) for f, a in s["by_field"].items()]
    out.append("by family")
    out += [_line(f, a) for f, a in s["by_family"].items()]
    out.append("by confidence")
    out += [_line(b["band"], b) for b in s["by_band"]]
    out.append("agreement")
    out.append("  " + "  ".join(f"{k} {v}" for k, v in s["agreement"].items()))
    out.append(f"threshold (target {s['target']})")
    out += [f"  {f:<24} {'none' if t is None else round(t, 4)}" for f, t in s["thresholds"].items()]
    return "\n".join(out)
