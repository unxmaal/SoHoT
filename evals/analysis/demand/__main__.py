"""python -m evals.analysis.demand census|codebook|report. #1151."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from evals import redact
from evals.analysis import demand as d


def _now(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _census(args) -> int:
    out = Path(args.out)
    frame = d.census(out, args.root, _now(args.now), args.days, args.n, args.seed)
    print(f"population {frame['population']} subtasks {frame['totals']['kinds']}, skipped {frame['skipped']}")
    print(f"sample {frame['n']} over {len(frame['strata'])} strata (project/candidate/size); N n fraction:")
    for s, v in frame["strata"].items():
        print(f"  {s} {v['N']} {v['n']} {v['fraction']:.3f}")
    print(f"packets: {out / 'packets-a.jsonl'}, {out / 'packets-b.jsonl'}; frame: {out / 'frame.json'}")
    return 0


def _codebook(args) -> int:
    print(d.LOCAL)
    for k, table in d.CLOSED.items():
        print(f"\n{k}:")
        for name, what in table.items():
            print(f"  {name}: {what}")
    print(f"\n{d.LATENCY_RULE}")
    return 0


def _report(args) -> int:
    frame = json.loads((Path(args.dir) / "frame.json").read_text(encoding="utf-8"))
    a, b = d.load_rounds(args.a), d.load_rounds(args.b)
    settled = d.load_labels(Path(args.settled)) if args.settled else None
    got = d.report(frame, a, b, settled)
    print(d.text(frame, got), end="")
    if args.disagreements:
        for row in got["disagreements"]:
            print(json.dumps(row))
    if args.write:
        known = redact.known_here()
        for p in d.write(Path(args.write), frame, got, d.manifest(frame, a, b, settled, known), known):
            print(f"wrote {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.analysis.demand", description=d.__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("census", help="scan transcripts, draw the stratified sample, write redacted packets")
    c.add_argument("--out", required=True, help="a working directory outside the repo's tracked tree")
    c.add_argument("--root", default=None, help="the Claude Code projects directory (default ~/.claude/projects)")
    c.add_argument("--now", default=None, help="window end, ISO time or epoch seconds (default: now)")
    c.add_argument("--days", type=int, default=d.DAYS)
    c.add_argument("--n", type=int, default=d.SAMPLE)
    c.add_argument("--seed", type=int, default=d.SEED)
    c.set_defaults(fn=_census)
    k = sub.add_parser("codebook", help="the label sets and what the local side can do, as labellers see them")
    k.set_defaults(fn=_codebook)
    r = sub.add_parser("report", help="kappa and the weighted shape x fit x latency table from two label files")
    r.add_argument("dir", help="the census --out directory")
    r.add_argument("--a", required=True, action="append", help="labeller A's file; repeat for a later round")
    r.add_argument("--b", required=True, action="append", help="labeller B's file; repeat for a later round")
    r.add_argument("--settled", default=None, help="labels that settle the units A and B disagree on")
    r.add_argument("--disagreements", action="store_true")
    r.add_argument("--write", default=None, help=f"write manifest.jsonl, strata.json, census.txt here ({d.HERE})")
    r.set_defaults(fn=_report)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
