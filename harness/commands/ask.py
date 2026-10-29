"""`soh ask PATH... -q QUESTION`: a local model reads the files and answers, the way local_complete does with paths. #1335."""
from __future__ import annotations

import os
from pathlib import Path

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    from harness import ask
    p = sub.add_parser("ask", help="answer a question about long log or tool-output files with a local "
                       "model; --redo measures how often a digest was followed by a full Read; --eval DIR "
                       "runs the planted-failure eval")
    p.add_argument("paths", nargs="*", help="files under this worktree, Claude Code's tool-results, "
                   f"SoHoT's logs or ${ask.ROOTS_ENV}")
    p.add_argument("-q", "--question", default="", help="what to find in the files")
    p.add_argument("--lane", default="extract", help="extract (default) or code for diffs and tracebacks")
    p.add_argument("--max-tokens", type=int, default=ask.REPLY_TOKENS)
    p.add_argument("--redo", action="store_true", help="digests in the transcripts and the share redone by a "
                   f"full Read within {ask.REDO_WINDOW} tool calls")
    p.add_argument("--since", default="7d", help="--redo window: 7d, 12h")
    p.add_argument("--root", default="", help="--redo transcripts root (default $SOH_CLAUDE_PROJECTS or ~/.claude/projects)")
    p.add_argument("--eval", default="", metavar="DIR", help="write the synthesized logs to DIR and score the lane on them")
    p.add_argument("--n", type=int, default=60, help="--eval: logs, each with a clean twin")
    p.add_argument("--seed", type=int, default=None, help="--eval: the set's generator seed (pytest 1335, fresh 2026, third 4711)")
    p.add_argument("--set", default="pytest", choices=("pytest", "fresh", "third"), help="--eval: pytest-shaped "
                   "logs, fresh go/jest/cargo/lint/gradle logs, or third unittest/rspec/C/terraform logs")
    p.add_argument("--chunk", type=int, default=0, help="characters per part (default: the lane's, see ask_chunk_chars)")
    p.add_argument("--live-home", action="store_true", help="--eval/--redo: run in the live home and write its "
                   "store; without it they run from a scratch home (DIR/home for --eval) #1346")
    p.set_defaults(func=cmd_ask)


def scratch_home(a, scratch: Path) -> str:
    """Point this process at `scratch` unless the home was named; an error when that is the live home. #1346"""
    from harness import paths
    if a.live_home:
        return ""
    named = os.environ.get(paths.ENV_VAR)
    if named:
        live = paths.is_live(paths.home() / "discovery.db")
        return f"{paths.ENV_VAR} names the live home; pass --live-home to write its store" if live else ""
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ[paths.ENV_VAR] = str(scratch)
    return ""


def cmd_ask(a) -> int:
    if a.redo or a.eval:
        import tempfile
        scratch = Path(a.eval).expanduser().resolve() / "home" if a.eval else Path(tempfile.mkdtemp(prefix="soh-redo-"))
        refused = scratch_home(a, scratch)
        if refused:
            note(refused)
            emit(False, error=refused)
            return 2
        return _redo(a) if a.redo else _eval(a)
    from harness import ask, completion
    if not a.paths or not a.question.strip():
        note("give one or more paths and -q QUESTION")
        emit(False, error="paths and a question")
        return 2
    try:
        got = ask.ask(a.paths, a.question, lane=a.lane, cwd=Path.cwd(), max_tokens=a.max_tokens,
                      size=a.chunk or None)
    except (ValueError, completion.CompletionError) as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 1
    note(got["text"])
    note(f"-- {got['model']}, {got['parts']} part(s), {got['calls']} call(s), {got['seconds']:.1f}s: "
         + ", ".join(f"{f['path']} ({f['bytes']} bytes)" for f in got["files"]))
    emit(**got)
    return 0


def _redo(a) -> int:
    import time

    from harness import ask, context_report as cr
    try:
        since = cr.parse_when(a.since, time.time())
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    root = Path(a.root).expanduser() if a.root else cr.default_root()
    got = ask.redos(cr.transcripts(root, newer_than=since), since=since)
    rate = "--" if got["rate"] is None else f"{got['rate']:.0%}"
    note(f"{got['digests']} digests by path, {got['redos']} redone by a full Read within "
         f"{ask.REDO_WINDOW} tool calls ({rate}; the bar is 15%)")
    for e in got["examples"]:
        note(f"  {e['path']}  in {e['transcript']}")
    emit(**got)
    return 0


def _eval(a) -> int:
    from evals import ask_plants
    from harness import ask
    out = Path(a.eval).expanduser().resolve()

    def answer(path: str, question: str) -> str:
        return ask.ask([path], question, lane=a.lane, roots=[ask.Root(out)],
                       max_tokens=a.max_tokens, size=a.chunk or None)["text"]

    def progress(r) -> None:
        note(f"{r['id']:<28} {'hit ' if r['hit'] else 'MISS'} {'none' if r['clean_none'] else 'NOISE'}"
             + (f"  {r['error']}" if r.get("error") else ""))
    got = ask_plants.run(out, answer, n=a.n, seed=a.seed, progress=progress, family=a.set)
    note(f"planted named {got['hits']}/{got['logs']} ({got['hit_rate']:.0%}, Wilson lower {got['hit_lower']:.2f}); "
         f"clean answered none {got['nones']}/{got['clean']} ({got['none_rate']:.0%}); "
         f"{'passes' if got['passes'] else 'does not pass'} the bars; rows in {out / 'results.jsonl'}")
    emit(**got)
    return 0 if got["passes"] else 1
