"""Repo-lane failure taxonomy: tally run directories, check every cited excerpt, read each arm's receipt back. #921."""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

LABELS = Path(__file__).resolve().parent / "repo_failure_labels.jsonl"

#: Label class -> whose fault it is: the model, the lane's prompt or protocol, or the harness.
CODEBOOK = {
    "budget_exhausted": "harness",
    "tool_call": "protocol",
    "malformed_hunk": "model",
    "context_mismatch": "model",
    "no_diff": "model",
    "wrong_fix": "model",
    "regression": "model",
    "recount_header": "harness",
}
#: One line per class, for a labeller who sees only this and the evidence.
DEFINITIONS = {
    "budget_exhausted": "the runner says the reply spent max_tokens with no answer; at_cut says what the reasoning was "
                        "doing at the cut, or unrecorded when the run kept no reasoning",
    "tool_call": "the reply holds no diff and calls tools instead (<tool_call>, <function=...>), as an agent would",
    "no_diff": "the reply holds no diff and no tool call: prose, a refusal, or code outside a unified diff",
    "malformed_hunk": "a hunk header git cannot parse, such as `@@ def name(...)` or `@@ -def ...` with no line ranges",
    "recount_header": "git apply --recount rejects a diff only because a file has no `diff --git` line, so the next "
                      "file's ---/+++ headers count as hunk lines; it applies once one is added before each `--- ` (#940)",
    "context_mismatch": "the hunks parse, but their context or removed lines are not in the base file, so git apply "
                        "--recount fails (\"patch failed: <file>:<line>\")",
    "wrong_fix": "the patch applied and at least one fail_to_pass test still fails",
    "regression": "the patch applied, every fail_to_pass test passes, and a pass_to_pass test now fails",
}
#: The first class that fits wins: a row is labelled by the earliest step it failed at.
PRECEDENCE = ("budget_exhausted", "tool_call", "no_diff", "malformed_hunk", "recount_header", "context_mismatch",
              "wrong_fix", "regression")
#: What a budget-exhausted reply's reasoning was doing when the budget cut it; unrecorded when the run kept none.
AT_CUT = ("looping", "rereading", "drafting_diff", "other", "unrecorded")
#: The runner's own classes, in the order the issue's table reports them.
TALLY = ("pass", "token_budget_exhausted", "invalid_patch", "content_failed", "environment_error")
UNLABELLED = ("environment_error",)

#: The rerun arms as evals.run arguments: A redraws run 466, B is thinking off, C the vendor sampler on the ladder.
ORNITH = "llamacpp:Ornith-1.5-35B-Q4_K_M"
RUN = ["uv", "run", "python", "-m", "evals.run", "--modality", "repo", "--repeat", "1", "--split", "all"]
ARMS = {
    "A": ["--candidates", ORNITH],
    "B": ["--candidates", f"{ORNITH},enable_thinking=false", "--max-tokens", "32768"],
    "C": ["--candidates", f"{ORNITH},enable_thinking=true,temperature=1.0,top_p=0.95,top_k=20,min_p=0,"
          "presence_penalty=0", "--budget-ladder", "32768,65536"],
}


def arm_command(arm: str, out: str) -> list[str]:
    return [*RUN, *ARMS[arm], "--out", out]


def expected(arm: str) -> dict:
    """The request every case of `arm` must have been sent, from its arguments as the run reads them."""
    from harness import completion, serving
    args = dict(zip(ARMS[arm][::2], ARMS[arm][1::2]))
    _, _, optstr = args["--candidates"].partition(",")
    lane = {"temperature": completion.DEFAULT_TEMPERATURE, **completion.SAMPLING.get("repo", {})}
    budgets = (tuple(int(x) for x in args["--budget-ladder"].split(",")) if "--budget-ladder" in args
               else (int(args.get("--max-tokens") or completion.budget("repo")),))
    return {"template": serving.template_options(optstr, args["--candidates"]),
            "sampling": {**lane, **serving._sampling(optstr, args["--candidates"])},
            "max_tokens": budgets}


@dataclass
class Run:
    path: Path
    receipt: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name


def load_run(path) -> Run:
    """A run directory's receipt and rows, from results.json, else from a paused run's checkpoint."""
    path = Path(path)
    results = path / "results.json"
    if results.is_file():
        got = json.loads(results.read_text(encoding="utf-8"))
        return Run(path, got.get("receipt") or {}, list(got.get("rows") or []))
    rows, identity = [], {}
    for line in (path / "checkpoint.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line) if line.strip() else {}
        identity = entry.get("identity") or identity
        if "row" in entry:
            rows.append(entry["row"])
    return Run(path, identity, rows)


def outcome(row: dict) -> str:
    return "pass" if row.get("passed") else (row.get("failure_class") or "unclassed")


def tally(run: Run) -> Counter:
    return Counter(outcome(r) for r in run.rows)


def load_labels(path=LABELS) -> list[dict]:
    """The committed labels, each checked against the codebook; a bad line is refused, never skipped."""
    out = []
    path = Path(path)
    if not path.is_file():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        got = json.loads(line)
        missing = {"run", "case", "class", "file", "offset", "excerpt"} - set(got)
        if missing:
            raise ValueError(f"{path.name}:{n}: missing {', '.join(sorted(missing))}")
        if got["class"] not in CODEBOOK:
            raise ValueError(f"{path.name}:{n}: class {got['class']!r} is not in the codebook")
        if got["class"] == "budget_exhausted" and got.get("at_cut") not in AT_CUT:
            raise ValueError(f"{path.name}:{n}: budget_exhausted needs at_cut, one of {', '.join(AT_CUT)}")
        out.append(got)
    return out


def check_excerpt(run_dir, label: dict) -> str:
    """"" when the label's excerpt is the bytes at its offset in its file under the run directory, else why not."""
    root = Path(run_dir).resolve()
    f = (root / label["file"]).resolve()
    if root not in f.parents:
        return f"{label['file']} is outside the run directory"
    if not f.is_file():
        return f"{label['file']} is not in {root.name}"
    want = label["excerpt"].encode("utf-8")
    at = int(label["offset"])
    got = f.read_bytes()[at:at + len(want)]
    return "" if got == want else f"{label['file']}@{at} reads {got[:60]!r}, not the cited excerpt"


def unlabelled(run: Run, labels: list[dict]) -> list[str]:
    """Failing rows of `run` no label covers, environment errors aside (#913 owns those)."""
    have = {lab["case"] for lab in labels if lab["run"] == run.name}
    return sorted(r["case_id"] for r in run.rows
                  if not r.get("passed") and r.get("failure_class") not in UNLABELLED
                  and r["case_id"] not in have)


def kappa(a: list[dict], b: list[dict]) -> tuple[float | None, int]:
    """Cohen's kappa of two labellers over the (run, case) rows both labelled, and how many that is."""
    mine = {(x["run"], x["case"]): x["class"] for x in a}
    theirs = {(x["run"], x["case"]): x["class"] for x in b}
    shared = sorted(set(mine) & set(theirs))
    if not shared:
        return None, 0
    n = len(shared)
    observed = sum(mine[k] == theirs[k] for k in shared) / n
    ca, cb = Counter(mine[k] for k in shared), Counter(theirs[k] for k in shared)
    expected = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / (n * n)
    if expected == 1.0:
        return (1.0 if observed == 1.0 else 0.0), n
    return (observed - expected) / (1 - expected), n


def sample(runs: list[Run], n: int, seed: int, stratify: bool = False, skip=()) -> list[tuple[str, str]]:
    """A seeded random `n` of the labellable rows; stratified, an even share of each (run, runner class)."""
    strata: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for run in runs:
        for r in run.rows:
            cls = r.get("failure_class")
            if not r.get("passed") and cls not in UNLABELLED and cls not in skip:
                strata.setdefault((run.name, cls) if stratify else ("", ""), []).append((run.name, r["case_id"]))
    rng = random.Random(seed)
    pools = {k: rng.sample(sorted(v), len(v)) for k, v in sorted(strata.items())}
    take = dict.fromkeys(pools, 0)
    while sum(take.values()) < n and any(take[k] < len(pools[k]) for k in pools):
        open_ = [k for k in pools if take[k] < len(pools[k])]
        k = min(open_, key=lambda k: (take[k], -len(pools[k]), k))
        take[k] += 1
    return sorted(x for k in pools for x in pools[k][:take[k]])


def disagreements(a: list[dict], b: list[dict]) -> list[tuple[str, str, str, str]]:
    """(run, case, a's class, b's class) for each row both labelled differently."""
    mine = {(x["run"], x["case"]): x["class"] for x in a}
    theirs = {(x["run"], x["case"]): x["class"] for x in b}
    return [(*k, mine[k], theirs[k]) for k in sorted(set(mine) & set(theirs)) if mine[k] != theirs[k]]


def arm_check(receipt: dict, arm: str) -> list[str]:
    """What this run's receipt says it sent that arm `arm` did not ask for; [] when every request matches."""
    want = expected(arm)
    sent = [r for got in (receipt.get("requests") or {}).values() for r in got]
    if not sent:
        return ["the receipt records no requests: it predates #921 or ran no text candidate"]
    out = []
    for r in sent:
        if dict(r.get("template") or {}) != want["template"]:
            out.append(f"template {r.get('template')} is not {want['template']}")
        if dict(r.get("sampling") or {}) != want["sampling"]:
            out.append(f"sampling {r.get('sampling')} is not {want['sampling']}")
        if r.get("max_tokens") not in want["max_tokens"]:
            out.append(f"max_tokens {r.get('max_tokens')} is not one of {list(want['max_tokens'])}")
    return sorted(set(out))


def locate(path, text: str) -> list[int]:
    """Every byte offset `text` starts at in `path`, so a label can cite it."""
    data, want, out, at = Path(path).read_bytes(), text.encode("utf-8"), [], 0
    while (at := data.find(want, at)) >= 0:
        out.append(at)
        at += 1
    return out


def _tally(args) -> int:
    runs = [load_run(p) for p in args.runs]
    labels = load_labels(args.labels)
    print(f"{'run':40} {'rows':>4} " + " ".join(f"{c[:12]:>12}" for c in TALLY) + "  other")
    for run in runs:
        got = tally(run)
        other = sum(v for k, v in got.items() if k not in TALLY)
        print(f"{run.name:40} {len(run.rows):>4} " + " ".join(f"{got[c]:>12}" for c in TALLY) + f"  {other}")
    bad, missing = [], {}
    for run in runs:
        mine = [lab for lab in labels if lab["run"] == run.name]
        bad += [f"{run.name} {lab['case']}: {why}" for lab in mine if (why := check_excerpt(run.path, lab))]
        classes = Counter(lab["class"] for lab in mine)
        if classes:
            print(f"\n{run.name} labels: " + ", ".join(
                f"{c} {n} ({CODEBOOK[c]})" for c, n in sorted(classes.items())))
            cuts = Counter(lab.get("at_cut") for lab in mine if lab["class"] == "budget_exhausted")
            if cuts:
                print("  at the cut: " + ", ".join(f"{c} {n}" for c, n in sorted(cuts.items())))
        missing[run.name] = unlabelled(run, labels)
    for name, cases in missing.items():
        if cases:
            print(f"\n{name}: {len(cases)} failing row(s) unlabelled: {', '.join(cases)}")
    for line in bad:
        print(f"excerpt: {line}", file=sys.stderr)
    return 1 if bad or (args.complete and any(missing.values())) else 0


def _receipt(args) -> int:
    run = load_run(args.run)
    r = run.receipt
    lane = r.get("modality", "")
    print(f"{run.name}: {lane}, {len(r.get('case_ids') or [])} cases, max_tokens {r.get('max_tokens')}, "
          f"ladder {r.get('budget_ladder') or 'none'}")
    print(f"  template: {(r.get('template') or {}).get(lane, 'none sent') if r.get('template') is not None else 'unrecorded'}")
    print(f"  sampling: {(r.get('sampling') or {}).get(lane)}")
    for key, sent in sorted((r.get("requests") or {}).items()):
        for one in sent:
            print(f"  sent by {key}: {json.dumps(one, sort_keys=True)}")
    for key, got in sorted((r.get("server_sampling") or {}).items()):
        print(f"  server default for {key}: {json.dumps(got, sort_keys=True)}")
    if not args.arm:
        return 0
    wrong = arm_check(r, args.arm)
    for line in wrong:
        print(f"arm {args.arm}: {line}", file=sys.stderr)
    return 1 if wrong else 0


def _arms(args) -> int:
    import shlex
    from harness import paths
    root = Path(args.root).expanduser() if args.root else paths.runs()
    for arm in sorted(ARMS):
        print(shlex.join(arm_command(arm, str(root / f"921-arm-{arm.lower()}"))))
    return 0


def _codebook(args) -> int:
    for cls in PRECEDENCE:
        print(f"{cls} ({CODEBOOK[cls]}): {DEFINITIONS[cls]}")
    print(f"\nThe first class that fits wins, in the order above. at_cut is one of {', '.join(AT_CUT)}.")
    return 0


def _sample(args) -> int:
    for run, case in sample([load_run(p) for p in args.runs], args.n, args.seed, args.stratify, args.skip):
        print(f"{run}\t{case}")
    return 0


def _kappa(args) -> int:
    value, n = kappa(load_labels(args.a), load_labels(args.b))
    print("no rows labelled by both" if value is None else f"Cohen's kappa {value:.3f} over {n} rows")
    for run, case, x, y in disagreements(load_labels(args.a), load_labels(args.b)):
        print(f"  {run} {case}: {x} / {y}")
    return 0


def _locate(args) -> int:
    for at in locate(Path(args.run) / args.file, args.text):
        print(at)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.analysis.repo_failures", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tally", help="runner classes per run, label classes, excerpt check, unlabelled rows")
    t.add_argument("runs", nargs="+")
    t.add_argument("--labels", default=str(LABELS))
    t.add_argument("--complete", action="store_true", help="exit 1 while any failing row is unlabelled")
    t.set_defaults(fn=_tally)
    r = sub.add_parser("receipt", help="what the run's receipt says it sent; --arm checks it against an arm")
    r.add_argument("run")
    r.add_argument("--arm", choices=sorted(ARMS))
    r.set_defaults(fn=_receipt)
    a = sub.add_parser("arms", help="the evals.run command of each rerun arm")
    a.add_argument("--root", default=None, help="where the arms' run directories go (default: the runs directory)")
    a.set_defaults(fn=_arms)
    s = sub.add_parser("sample", help="a seeded random set of labellable rows for a blind second labeller")
    s.add_argument("runs", nargs="+")
    s.add_argument("--n", type=int, default=25)
    s.add_argument("--seed", type=int, default=921)
    s.add_argument("--stratify", action="store_true", help="an even share of each (run, runner class)")
    s.add_argument("--skip", action="append", default=[], help="a runner class to leave out; repeatable")
    s.set_defaults(fn=_sample)
    c = sub.add_parser("codebook", help="each label class, whose fault it is, its definition and precedence")
    c.set_defaults(fn=_codebook)
    k = sub.add_parser("kappa", help="Cohen's kappa of two label files over the rows both labelled")
    k.add_argument("a")
    k.add_argument("b")
    k.set_defaults(fn=_kappa)
    lo = sub.add_parser("locate", help="the byte offsets a text starts at in a run file")
    lo.add_argument("run")
    lo.add_argument("file")
    lo.add_argument("text")
    lo.set_defaults(fn=_locate)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
