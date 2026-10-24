"""Repo-lane failure taxonomy: tally run directories, check every cited excerpt, read each arm's receipt back. #921."""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from harness import reasons, yield_stop

LABELS = Path(__file__).resolve().parent / "repo_failure_labels.jsonl"
#: Rows graded again from their stored diffs (`soh cases regrade repo --json`), with the run each came from. #940.
REGRADES = LABELS.with_name("repo_regrades.jsonl")

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
#: Why a wrong_fix row failed, in #1141's hypothesis order, and whose fault that is.
GRADINGS = {
    "pinned_detail": "case",
    "gold_internals": "case",
    "environment": "harness",
    "apply_mangled": "harness",
    "genuine": "model",
}
GRADING_DEFINITIONS = {
    "pinned_detail": "the change does what the prompt asks, but a hidden test requires a detail the prompt, its "
                     "tests-call block and the context files do not state: a name, signature, location, message, "
                     "return shape, key, constant or threshold",
    "gold_internals": "the fix behaves as the gold fix does, but a test inspects the gold fix's mechanism (a mocked "
                      "private helper, call counts, a private attribute) rather than behaviour",
    "environment": "the test fails for a reason no fix could change: a missing fixture, ordering, the network, the "
                   "sandbox, an id that does not collect; the gold fix fails the same way",
    "apply_mangled": "the tree the tests ran on is not what the stored diff says",
    "genuine": "the fix is wrong or incomplete on behaviour the prompt states or clearly implies; a row with any "
               "such failing test is genuine whatever else it fails on",
}
#: The first class that fits wins: a row is labelled by the earliest step it failed at.
PRECEDENCE = ("budget_exhausted", "tool_call", "no_diff", "malformed_hunk", "recount_header", "context_mismatch",
              "wrong_fix", "regression")
#: What a budget-exhausted reply's reasoning was doing when the budget cut it; unrecorded when the run kept none.
AT_CUT = ("looping", "rereading", "drafting_diff", "other", "unrecorded")
#: The runner's own classes, in the order the issue's table reports them.
TALLY = ("pass", "token_budget_exhausted", "tool_call", "invalid_patch", "content_failed", "environment_error")
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
        if "grading" in got and (got["class"] != "wrong_fix" or got["grading"] not in GRADINGS):
            raise ValueError(f"{path.name}:{n}: grading {got['grading']!r} needs class wrong_fix and one of "
                             f"{', '.join(GRADINGS)}")
        out.append(got)
    return out


def load_regrades(path=REGRADES) -> dict:
    """{(run, case): regrade row}; a row missing a key is refused."""
    out, path = {}, Path(path)
    if not path.is_file():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            got = json.loads(line)
            missing = {"run", "case", "file", "resolved", "patch_applied", "detail"} - set(got)
            if missing:
                raise ValueError(f"{path.name}:{n}: missing {', '.join(sorted(missing))}")
            out[(got["run"], got["case"])] = got
    return out


def check_excerpt(run_dir, label: dict, regrades=None) -> str:
    """"" when the label's excerpt is the bytes at its offset in its file (or its regrade's detail), else why not."""
    if label.get("regrade"):
        again = (regrades or {}).get((Path(run_dir).name, label["case"]))
        if again is None:
            return "no regrade of this row"
        want, at = label["excerpt"].encode("utf-8"), int(label["offset"])
        # A label citing a test is checked in that test's kept failure text, else in the detail. #1141.
        where = (again.get("failures") or {}).get(label["test"]) if label.get("test") else again["detail"]
        if where is None:
            return f"the regrade kept no failure text for {label['test']}"
        got = where.encode("utf-8")[at:at + len(want)]
        name = label.get("test") or "detail"
        return "" if got == want else f"regrade {name}@{at} reads {got[:60]!r}, not the cited excerpt"
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


def unlabelled(run: Run, labels: list[dict], regrades=None) -> list[str]:
    """Failing rows of `run` no label covers, environment errors and rows a regrade resolved aside."""
    have = {lab["case"] for lab in labels if lab["run"] == run.name}
    fixed = {c for (r, c), g in (regrades or {}).items() if r == run.name and g["resolved"]}
    return sorted(r["case_id"] for r in run.rows
                  if not r.get("passed") and r.get("failure_class") not in UNLABELLED
                  and r["case_id"] not in have | fixed)


def kappa(a: list[dict], b: list[dict], key: str = "class") -> tuple[float | None, int]:
    """Cohen's kappa of two labellers over the (run, case) rows both labelled with `key`, and how many that is."""
    mine = {(x["run"], x["case"]): x[key] for x in a if key in x}
    theirs = {(x["run"], x["case"]): x[key] for x in b if key in x}
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


def disagreements(a: list[dict], b: list[dict], key: str = "class") -> list[tuple[str, str, str, str]]:
    """(run, case, a's `key`, b's `key`) for each row both labelled differently."""
    mine = {(x["run"], x["case"]): x[key] for x in a if key in x}
    theirs = {(x["run"], x["case"]): x[key] for x in b if key in x}
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


CASES = Path(__file__).resolve().parents[1] / "cases" / "repo"
#: What `causes` reads off a row with no labeller: the codebook's classes, the budget split by whether an answer began.
#: Runner classes `causes` reports as the runner named them, with no finer reading off the reply. #1170.
AS_RUN = (reasons.STOPPED_LOW_YIELD, reasons.TOOL_CALL, reasons.ENVIRONMENT_ERROR, reasons.DEGENERATE,
          reasons.RUNAWAY, reasons.TIMEOUT, reasons.STEP_CAP, reasons.CONTEXT_EXCEEDED, reasons.PLAN_REFUSED,
          reasons.POOL_FULL, reasons.BLANK_OUTPUT, reasons.BACKEND_FAULT, reasons.SERVER_DEAD, reasons.GPU_FAULT,
          reasons.REFUSED_BY_GATEWAY, reasons.HARNESS_ERROR, reasons.LOAD_LOG_UNREAD, reasons.SHORT_COPY,
          reasons.INCOMPLETE_COPY, reasons.ATTACHMENT, reasons.MISSING_PACKAGE, reasons.LOAD_FAILED_RUNTIME,
          reasons.LOAD_FAILED_FILE, reasons.LOAD_FAILED_LAYOUT, reasons.MISSING_FILE_IN_SNAPSHOT)
CAUSES = ("pass", "budget_no_answer", "budget_cut_answer", "no_diff", "malformed_hunk", "missing_file",
          "context_mismatch", "wrong_fix", "regression", "provider_refused", "crashed", *AS_RUN, "unclassed")
#: Causes of a reply cut before the grader saw it.
CUT = ("budget_no_answer", "budget_cut_answer", reasons.STOPPED_LOW_YIELD, reasons.DEGENERATE)
#: A crashed row whose provider's usage-policy screen refused the prompt: no reply exists to grade. #1136.
_REFUSED = re.compile(r"safeguards flagged|anthropic\.com/legal/aup|usage polic", re.I)
_TOOL = re.compile(r"<tool_call>|<function=")
_RANGED = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_MALFORMED = ("garbage", "corrupt patch", "No valid patches", "without header")


def _read(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def cause(row: dict, stored: dict) -> str:
    """The class a row fails at, read from the runner's class, the stored reply and its grade."""
    fc, detail = row.get("failure_class") or "", str(row.get("detail") or "")
    reply, diff = str(stored.get("reply") or ""), str(stored.get("diff") or "")
    if row.get("passed"):
        return "pass"
    if fc in AS_RUN:
        return fc
    if fc == "token_budget_exhausted":
        return "budget_cut_answer" if reply.strip() else "budget_no_answer"
    if fc == "invalid_patch":
        if not diff.strip():
            return "tool_call" if _TOOL.search(reply) else "no_diff"
        hunks = [x for x in diff.splitlines() if x.startswith("@@")]
        if any(m in detail for m in _MALFORMED) or any(not _RANGED.match(h) for h in hunks):
            return "malformed_hunk"
        if "No such file or directory" in detail:
            return "missing_file"
        return "context_mismatch" if "patch failed" in detail else "unclassed"
    if fc == "content_failed":
        return "wrong_fix" if "fail_to_pass still failing" in detail else "regression"
    if fc == "crashed":
        return "provider_refused" if _REFUSED.search(detail) else "crashed"
    return "unclassed"


def case_groups(root=CASES, old=()) -> dict:
    """Case id -> the case directory it was imported into, or "old" for an id in `old`."""
    out = {f.stem: (f.parent.name if f.parent != Path(root) else "repo") for f in Path(root).rglob("*.yaml")}
    return {**out, **{c: "old" for c in old}}


def causes(run: Run, groups: dict) -> list[dict]:
    """Per row: its group, cause, prompt and completion tokens and finish reason from the trajectory."""
    out = []
    for row in run.rows:
        case = row.get("case_id") or ""
        stem = f"{str(row.get('candidate') or '').replace('/', '_')}--{case}"
        stored = _read(run.path / f"{stem}.json")
        last = ((_read(run.path / f"{stem}.trajectory.json").get("requests") or [{}])[-1]) or {}
        out.append({"case": case, "group": groups.get(case, "unknown"), "cause": cause(row, stored),
                    "prompt_tokens": last.get("prompt_tokens"), "completion_tokens": last.get("completion_tokens"),
                    "finish": last.get("finish_reason")})
    return out


def _median(xs) -> str:
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    return "-" if not xs else f"{(xs[(len(xs) - 1) // 2] + xs[len(xs) // 2]) / 2:g}"


def cause_table(rows: list[dict]) -> str:
    """Cause x group counts, then per group the rows, the cut share and median prompt and uncut completion tokens."""
    groups = sorted({r["group"] for r in rows})
    n = Counter((r["cause"], r["group"]) for r in rows)
    lines = ["| cause | " + " | ".join(groups) + " | total |", "|---" * (len(groups) + 2) + "|"]
    for c in CAUSES:
        if any(n[(c, g)] for g in groups):
            lines.append(f"| {c} | " + " | ".join(str(n[(c, g)]) for g in groups)
                         + f" | {sum(n[(c, g)] for g in groups)} |")
    cut = set(CUT)
    lines.append("| rows | " + " | ".join(str(sum(r["group"] == g for r in rows)) for g in groups) + f" | {len(rows)} |")
    for label, fn in (("cut %", lambda rs: f"{100 * sum(r['cause'] in cut for r in rs) / len(rs):.0f}"),
                      ("median prompt tokens", lambda rs: _median(r["prompt_tokens"] for r in rs)),
                      ("median completion, uncut", lambda rs: _median(
                          r["completion_tokens"] for r in rs if r["cause"] not in cut))):
        lines.append(f"| {label} | " + " | ".join(fn([r for r in rows if r["group"] == g]) for g in groups)
                     + f" | {fn(rows) if rows else '-'} |")
    return "\n".join(lines)


def yield_stops(run: Run) -> list[dict]:
    """Per candidate the run stopped rows for: its stop point in tokens, rows stopped, explored, and run past it and passed."""
    out = []
    for cand in dict.fromkeys(str(r.get("candidate") or "") for r in run.rows):
        rows = [r for r in run.rows if str(r.get("candidate") or "") == cand]
        stops = [n for n in map(yield_stop.stopped_at, rows) if n is not None]
        point = ((run.receipt.get("yield_stop") or {}).get(cand)) or {}
        at = point.get("tokens") if isinstance(point.get("tokens"), int) else max(stops, default=None)
        if at is None or not stops:
            continue
        past = [r for r in rows if yield_stop.stopped_at(r) is None and (yield_stop.tokens_of(r) or 0) > at]
        explored = point.get("explored")
        out.append({"candidate": cand, "tokens": at, "stopped": len(stops),
                    "explored": len(explored) if isinstance(explored, list) else None,
                    "past": len(past), "passed_past": sum(bool(r.get("passed")) for r in past)})
    return out


def _causes(args) -> int:
    old = {r.get("case_id") for p in args.old for r in load_run(p).rows}
    groups = case_groups(args.cases, old)
    for path in args.runs:
        run = load_run(path)
        rows = causes(run, groups)
        print(f"{run.name}\n\n{cause_table(rows)}\n")
        for y in yield_stops(run):
            explored = "" if y["explored"] is None else f"{y['explored']} explored, "
            print(f"yield stop {y['candidate']}: {y['tokens']} tokens, {y['stopped']} row(s) stopped there; "
                  f"{explored}{y['past']} ran past it, {y['passed_past']} of them passed\n")
        if args.rows:
            for r in sorted(rows, key=lambda r: (CAUSES.index(r["cause"]), r["case"])):
                print(f"{r['cause']}\t{r['group']}\t{r['case']}\t{r['prompt_tokens']}\t{r['completion_tokens']}")
    return 0


def _tally(args) -> int:
    runs = [load_run(p) for p in args.runs]
    labels = load_labels(args.labels)
    regrades = load_regrades(args.regrades)
    print(f"{'run':40} {'rows':>4} " + " ".join(f"{c[:12]:>12}" for c in TALLY) + "  other")
    for run in runs:
        got = tally(run)
        other = sum(v for k, v in got.items() if k not in TALLY)
        print(f"{run.name:40} {len(run.rows):>4} " + " ".join(f"{got[c]:>12}" for c in TALLY) + f"  {other}")
    bad, missing = [], {}
    for run in runs:
        mine = [lab for lab in labels if lab["run"] == run.name]
        bad += [f"{run.name} {lab['case']}: {why}" for lab in mine
                if (why := check_excerpt(run.path, lab, regrades))]
        # A resolved regrade may keep a label only to say why the grade was unfair. #1141.
        bad += [f"{run.name} {case}: labelled, but its regrade resolved" for lab in mine
                if (g := regrades.get((run.name, case := lab["case"]))) and g["resolved"]
                and GRADINGS.get(lab.get("grading")) in (None, "model")]
        again = [g for (r, _), g in sorted(regrades.items()) if r == run.name]
        if again:
            print(f"\n{run.name} regraded: {len(again)}, now resolved: "
                  + (", ".join(g["case"] for g in again if g["resolved"]) or "none"))
        classes = Counter(lab["class"] for lab in mine)
        if classes:
            print(f"\n{run.name} labels: " + ", ".join(
                f"{c} {n} ({CODEBOOK[c]})" for c, n in sorted(classes.items())))
            cuts = Counter(lab.get("at_cut") for lab in mine if lab["class"] == "budget_exhausted")
            if cuts:
                print("  at the cut: " + ", ".join(f"{c} {n}" for c, n in sorted(cuts.items())))
            graded = Counter(lab["grading"] for lab in mine if "grading" in lab)
            if graded:
                print("  wrong_fix graded: " + ", ".join(
                    f"{g} {graded[g]} ({GRADINGS[g]})" for g in GRADINGS if graded[g]))
        missing[run.name] = unlabelled(run, labels, regrades)
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
    print("\nA wrong_fix row may carry a grading, why it failed (#1141):")
    for g in GRADINGS:
        print(f"{g} ({GRADINGS[g]}): {GRADING_DEFINITIONS[g]}")
    return 0


def _sample(args) -> int:
    for run, case in sample([load_run(p) for p in args.runs], args.n, args.seed, args.stratify, args.skip):
        print(f"{run}\t{case}")
    return 0


def _kappa(args) -> int:
    a, b = load_labels(args.a), load_labels(args.b)
    value, n = kappa(a, b, args.key)
    print("no rows labelled by both" if value is None else f"Cohen's kappa {value:.3f} over {n} rows")
    for run, case, x, y in disagreements(a, b, args.key):
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
    t.add_argument("--regrades", default=str(REGRADES), help="rows graded again from their stored diffs (#940)")
    t.add_argument("--complete", action="store_true", help="exit 1 while any failing row is unlabelled")
    t.set_defaults(fn=_tally)
    ca = sub.add_parser("causes", help="each row's class read off its reply and grade, counted by case group (#1128)")
    ca.add_argument("runs", nargs="+")
    ca.add_argument("--old", action="append", default=[], help="a run whose cases count as the group 'old'")
    ca.add_argument("--cases", default=str(CASES), help="the repo cases root the groups are read from")
    ca.add_argument("--rows", action="store_true", help="also print one line per row")
    ca.set_defaults(fn=_causes)
    r = sub.add_parser("receipt",help="what the run's receipt says it sent; --arm checks it against an arm")
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
    k.add_argument("--key", default="class", choices=("class", "grading"), help="the field compared (#1141)")
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
