"""`soh digest LOG...` or `soh digest --run -- CMD...`: a checked local digest of a log instead of reading it. #1690."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    p = sub.add_parser("digest", help="digest a long log or test output with a local model, checked for every "
                       "failing test and error line, with a pointer to the raw file; --run runs a command into a "
                       "log first; --ab DIR measures the read path on the recorded CI logs")
    p.add_argument("paths", nargs="*", help="log files, or with --run the command to run (after --)")
    p.add_argument("-q", "--question", default="", help="what to find (default: failing tests, errors, counts, exits)")
    p.add_argument("--lane", default="extract", help="extract (default) or code")
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--no-model", action="store_true", help="the failure scan and the check alone, no local model")
    p.add_argument("--run", action="store_true", help="run the command given after --, its output to --out, and "
                   "digest that; exits with the command's code")
    p.add_argument("--out", default="", help="--run: the log file (default $LOCALHARNESS_HOME/logs/digest/<time>.log)")
    p.add_argument("--ab", default="", metavar="DIR", help="score raw against digest on the recorded CI logs "
                   "(evals/digest_ab), from a scratch home in DIR/home")
    p.add_argument("--live-home", action="store_true", help="--ab: run in the live home and write its store")
    p.set_defaults(func=cmd_digest)


def _ab(a) -> int:
    from evals import digest_ab
    from harness import paths
    out = Path(a.ab).expanduser().resolve()
    try:
        paths.eval_home(out / "home", live=a.live_home)
    except paths.LiveHomeRefused as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2

    def progress(r) -> None:
        note(f"{r['id']:<12} raw {r['raw_tokens']:>7,} digest {r['digest_tokens']:>5,} tests {r['tests_checked']}/"
             f"{r['tests']} (model {r['tests_model']}, scan {r['tests_shipped']}) {r['seconds']:.0f}s"
             + (f"  no model: {r['unmodelled'][:80]}" if r["unmodelled"] else ""))
    rep = digest_ab.run(out, model=not a.no_model, lane=a.lane, progress=progress)
    for line in rep["lines"]:
        note(line)
    note(f"rows in {out / 'results.jsonl'}, report in {out / 'report.json'}")
    emit(**rep)
    return 0


def _ran(a) -> tuple[Path, int]:
    from harness import paths
    out = Path(a.out).expanduser() if a.out else paths.logs() / "digest" / time.strftime("%Y%m%d-%H%M%S.log")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        rc = subprocess.run(a.paths, stdout=fh, stderr=subprocess.STDOUT, check=False).returncode
    return out, rc


def cmd_digest(a) -> int:
    if a.ab:
        return _ab(a)
    from harness import ask, completion, delegations, digest
    if not a.paths:
        note("give log paths, or --run -- CMD...")
        emit(False, error="no paths")
        return 2
    rc, raws, roots = 0, a.paths, None
    if a.run:
        try:
            log, rc = _ran(a)
        except OSError as exc:
            note(f"{a.paths[0]}: {exc}")
            emit(False, error=str(exc))
            return 127
        raws, roots = [str(log)], [ask.Root(log.parent), *ask.default_roots(Path.cwd())]
    try:
        got = digest.run(raws, a.question, lane=a.lane, roots=roots, cwd=Path.cwd(), max_tokens=a.max_tokens,
                         model=not a.no_model)
    except (ValueError, completion.CompletionError) as exc:
        note(str(exc))
        emit(False, error=str(exc), exit=rc)
        return rc or 1
    if got.get("call_id"):
        got["report"] = delegations.instruction(got["call_id"], cli=True)
    note(got["text"])
    note(f"-- {got.get('model') or 'no model'}, {got.get('calls') or 0} call(s), {got.get('seconds') or 0:.1f}s"
         + (f", call_id {got['call_id']}" if got.get("call_id") else "") + (f"; command exit {rc}" if a.run else ""))
    if got.get("report"):
        note(got["report"])
    emit(**got, exit=rc)
    return rc
