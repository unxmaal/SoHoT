"""`soh kb-filter --eval`: does a local model keep the KB hits sessions went on to use? #1334."""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

from harness.commands.common import emit, note


def _row(name: str, r: dict) -> str:
    return (f"{name:<9} {r['recall']:>7.3f} {r['lower']:>7.3f} {r['kept_referenced']:>5}/{r['referenced']:<5} "
            f"{r['kept_hits']:>6}/{r['hits']:<6} {r['kept_share']:>6.1%}")


def _answer_hook(a, stdin, decide) -> int:
    """Claude Code reads the hook's stdout as the replacement result, so it prints that or nothing, on any failure too."""
    from harness import kb_filter as kf
    tag = "-strict" if a.strict else ""
    try:
        event = json.loads(stdin.read() or "{}")
        chosen = json.loads((Path(a.dir) / f"report{tag}.json").read_text(encoding="utf-8"))
        vocab = json.loads((Path(a.dir) / f"vocab{tag}.json").read_text(encoding="utf-8"))
        if decide is None and chosen.get("ship", {}).get("arm") in kf.LOCAL:
            from harness import delegate
            decide = delegate.decide
        got = kf.hook(event, chosen, vocab, decide)
    except Exception:  # noqa: BLE001 - a hook that fails shows the search whole
        got = None
    if got:
        print(json.dumps(got))
    return 0


def cmd_kb_filter(a, stdin=None, decide=None) -> int:
    from harness import context_report as cr
    from harness import kb_filter as kf
    from harness import paths

    if a.hook:
        return _answer_hook(a, stdin or sys.stdin, decide)
    if a.settings:
        where = paths.deploy_checkout()
        command = (f"uv run --quiet --project {where or '<deploy checkout>'} soh kb-filter --hook "
                   f"--dir {Path(a.dir).expanduser().resolve()}" + (" --strict" if a.strict else ""))
        block = kf.settings(command)
        note("add to ~/.claude/settings.json or a project's .claude/settings.json (not applied here):")
        note(json.dumps(block, indent=2))
        emit(settings=block)
        return 0
    paths.eval_home(reads_live=True)
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
    vocab = kf.vocabulary(tune)
    (out / f"vocab{tag}.json").write_text(json.dumps(vocab), encoding="utf-8")
    got = kf.report(tune, scored_held, decide, extract, k, [p for p in planted if p["key"] in decide], vocab)
    cuts = ", ".join(f"{arm} {cut:.3f}" for arm, cut in got["thresholds"].items())
    note(f"{got['held_out']} held-out searches (newest {a.days:g} days); cuts {cuts}, tuned on earlier searches "
         f"({got['tuning']} with decide scores); position arm at the decide arm's kept tokens")
    note(f"{'arm':<9} {'recall':>7} {'lower':>7} {'kept/referenced':>11} {'hits kept':>13} {'tokens':>6}")
    for name, r in got["arms"].items():
        note(_row(name, r))
    for name, r in got.get("planted_by_arm", {}).items():
        note(_row(f"planted {name}", r))
    vs = got["vs_position"]
    note(f"decide vs position on referenced hits: {vs['won']} kept only by decide, {vs['lost']} only by position, "
         f"p {vs['p']}")
    for name, vs in got["vs_lexical"].items():
        note(f"{name} vs lexical at {name}'s kept tokens: {vs['won']} kept only by {name}, {vs['lost']} only by "
             f"lexical, p {vs['p']}")
    for name, why in got["gates"].items():
        note(f"gate {name}: " + ("passes" if not why else "fails: " + "; ".join(why)))
    note(f"ships: {got['ship']['arm']}" + ("".join(f"; {w}" for w in got["ship"]["why"])))
    (out / f"report{tag}.json").write_text(json.dumps(got, indent=1), encoding="utf-8")
    emit(got["ship"]["arm"] != "none", **got)
    return 0
