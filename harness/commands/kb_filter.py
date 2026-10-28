"""`soh kb-filter --eval`: does a local model keep the KB hits sessions went on to use? #1334."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from harness.commands.common import emit, note


def _row(name: str, r: dict) -> str:
    return (f"{name:<9} {r['recall']:>7.3f} {r['lower']:>7.3f} {r['kept_referenced']:>5}/{r['referenced']:<5} "
            f"{r['kept_hits']:>6}/{r['hits']:<6} {r['kept_share']:>6.1%}")


def cmd_kb_filter(a) -> int:
    from harness import context_report as cr
    from harness import kb_filter as kf

    out = Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = "-strict" if a.strict else ""
    path = out / f"set{tag}.jsonl"
    if a.rebuild or not path.exists():
        root = Path(a.root) if a.root else cr.default_root()
        try:
            since = cr.parse_when(a.since, time.time())
        except ValueError as exc:
            note(str(exc))
            emit(False, error=str(exc))
            return 2
        items = kf.labelled(root, since=since, strict=a.strict)
        path.write_text("".join(json.dumps(it) + "\n" for it in items), encoding="utf-8")
        note(f"{len(items)} searches with a referenced hit since {a.since} -> {path}")
    items = kf.load(path)
    k = kf.Knobs(min_hits=a.min_hits, floor=a.floor, hit_chars=a.hit_chars, need_chars=a.need_chars,
                 chunk=a.chunk, reply=a.reply)
    tune, held = kf.split(items, a.days)
    sample = random.Random(1334).sample(tune, min(a.tune, len(tune)))
    planted = kf.plant(held)
    arms = [s for s in a.arms.split(",") if s]
    unknown = sorted(set(arms) - {"decide", "extract"})
    if unknown:
        note(f"model arms are decide and extract, not {', '.join(unknown)}")
        emit(False, error="unknown arm")
        return 2
    if not a.no_model:
        from harness import delegate
        calls = {"decide": delegate.decide, "extract": delegate.complete}
        for arm in arms:
            todo = held + (sample + planted if arm == "decide" else [])
            kf.score(todo, arm, out / f"{arm}.jsonl", calls[arm], k, log=note)
    decide = kf.scored(out / "decide.jsonl")
    extract = kf.scored(out / "extract.jsonl")
    scored_held = [it for it in held if it["key"] in decide]
    if not scored_held:
        note("no held-out search has decide scores yet: run without --no-model")
        emit(False, error="unscored")
        return 1
    if len(scored_held) < len(held):
        note(f"{len(held) - len(scored_held)} held-out searches have no decide scores yet and are left out")
    got = kf.report(tune, scored_held, decide, extract, k, [p for p in planted if p["key"] in decide])
    note(f"{got['held_out']} held-out searches (newest {a.days:g} days), threshold {got['threshold']:.3f} "
         f"tuned on {got['tuning']} earlier ones; position arm at the decide arm's kept tokens")
    note(f"{'arm':<9} {'recall':>7} {'lower':>7} {'kept/referenced':>11} {'hits kept':>13} {'tokens':>6}")
    for name, r in got["arms"].items():
        note(_row(name, r))
    if "planted" in got:
        note(_row("planted", got["planted"]))
    vs = got["vs_position"]
    note(f"decide vs position on referenced hits: {vs['won']} kept only by decide, {vs['lost']} only by position, "
         f"p {vs['p']}")
    note("gate: " + ("passes" if not got["gate"] else "fails: " + "; ".join(got["gate"])))
    (out / f"report{tag}.json").write_text(json.dumps(got, indent=1), encoding="utf-8")
    emit(not got["gate"], **got)
    return 0
