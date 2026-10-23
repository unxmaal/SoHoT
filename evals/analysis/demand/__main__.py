"""python -m evals.analysis.demand census|codebook|report|replay. #1151, #1161."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from evals import redact
from evals.analysis import demand as d
from evals.analysis.demand import replay as rp


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
    settled = d.load_labels(Path(args.settled), partial=True) if args.settled else None
    got = d.report(frame, a, b, settled)
    got["rounds"] = max(len(args.a), len(args.b))
    print(d.text(frame, got), end="")
    if args.disagreements:
        for row in got["disagreements"]:
            print(json.dumps(row))
    if args.write:
        known = redact.known_here()
        for p in d.write(Path(args.write), frame, got, d.manifest(frame, a, b, settled, known), known):
            print(f"wrote {p}")
    return 0


def _replay(args) -> int:
    out = Path(args.out)
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    if bad := [s for s in steps if s not in rp.STEPS]:
        raise ValueError(f"unknown step {', '.join(bad)}; steps are {', '.join(rp.STEPS)}")
    if "prepare" in steps:
        now = _now(args.now) or json.loads(Path(args.strata).read_text(encoding="utf-8"))["now"]
        meta = rp.prepare(out, Path(args.manifest), Path(args.root or rp.tr.default_root()), now, args.controls,
                          args.seed)
        print(f"prepared {meta['selected'] - len(meta['missing'])} of {meta['selected']} units; missing "
              f"{meta['missing']}; packets {out / 'packets.jsonl'}", flush=True)
    packets, meta = rp.load(out)
    if args.limit:
        packets = packets[:args.limit]
    cands = [c.strip() for c in args.candidates.split(",") if c.strip()] or [rp.ADOPTED]
    ask = (lambda prompt, system: rp.claude(prompt, system, args.judge_model))
    if "calibrate" in steps:
        rows = rp.calibrate(out, packets, ask, args.jobs)
        print(f"calibration: {len(rows)} graded plants in {out / 'calibration.jsonl'}", flush=True)
    if "local" in steps:
        from harness import exclusive
        with exclusive.held("eval", announce=lambda m: print(m, flush=True)):
            for cand in cands:
                for r in range(1, args.repeats + 1):
                    rows = rp.run_local(out, packets, r, candidate=cand)
                    print(f"{cand} replay {r}: {len(rows)} replies, {sum(1 for x in rows if x.get('error'))} failed",
                          flush=True)
    if "grade" in steps:
        for cand in cands:
            for r in range(1, args.repeats + 1):
                print(f"{cand} grades {r}: {len(rp.grade(out, packets, r, ask, args.jobs, cand))}", flush=True)
    if "report" in steps:
        cal = rp._jsonl(out / "calibration.jsonl")
        body = rp.text_all([rp.report(packets, *rp.results(out, args.repeats, c), cal, meta, c) for c in cands])
        (out / "report.txt").write_text(body, encoding="utf-8")
        print(body, end="")
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
    p = sub.add_parser("replay", help="replay the manifest's local-fit units on the local lanes and grade them blind")
    p.add_argument("--out", required=True, help="a working directory outside the repo's tracked tree")
    p.add_argument("--manifest", default=str(d.HERE / "manifest.jsonl"))
    p.add_argument("--strata", default=str(d.HERE / "strata.json"), help="the census frame whose now the scan used")
    p.add_argument("--root", default=None, help="the Claude Code projects directory (default ~/.claude/projects)")
    p.add_argument("--now", default=None, help="override the census window end, ISO time or epoch seconds")
    p.add_argument("--steps", default="prepare,local,grade,report",
                   help="comma-separated, in order: prepare, calibrate, local, grade, report")
    p.add_argument("--controls", type=int, default=rp.CONTROLS, help="does-not-fit units drawn as the control")
    p.add_argument("--seed", type=int, default=rp.SEED)
    p.add_argument("--repeats", type=int, default=rp.REPEATS, help="replays at temperature 0, for grade agreement")
    p.add_argument("--candidates", default=rp.ADOPTED,
                   help=f"comma-separated model specs to replay every unit on; {rp.ADOPTED} is each lane's adopted model")
    p.add_argument("--judge-model", default=rp.JUDGE_MODEL)
    p.add_argument("--jobs", type=int, default=rp.JUDGE_JOBS, help="judge calls at once (cloud, no GPU)")
    p.add_argument("--limit", type=int, default=0, help="only the first N packets")
    p.set_defaults(fn=_replay)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
