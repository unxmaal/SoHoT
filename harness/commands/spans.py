"""`soh spans PATH -q QUESTION`: the lines of a file you will not edit that answer a question, checked against the file. #1336."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    from harness import spans
    p = sub.add_parser("spans", help="for a file you will read but not edit: a local model quotes the lines that "
                       "answer QUESTION, each quote checked against the file, else the whole file; --redo measures "
                       "full Reads that followed; --eval DIR scores span recall on past Reads")
    p.add_argument("path", nargs="?", default="", help="the file to read")
    p.add_argument("-q", "--question", default="", help="what you need from the file")
    p.add_argument("--lane", default="code", help="the lane whose model picks the spans (default code)")
    p.add_argument("-m", "--model", default=None, help="a model spec in place of the lane's adopted one")
    p.add_argument("--max-tokens", type=int, default=None, help=f"reply budget (default {spans.REPLY_TOKENS})")
    p.add_argument("--redo", action="store_true", help="spans calls in the transcripts and the share followed by "
                   f"a full Read of the same file within {spans.REDO_WINDOW} tool calls")
    p.add_argument("--eval", default="", metavar="DIR", help="score span recall on past exploratory Reads; rows "
                   "(numbers only) go to DIR/results.jsonl")
    p.add_argument("--kind", action="append", default=None, help="--eval: python, markdown or tests (repeatable; default all)")
    p.add_argument("--n", type=int, default=100, help="--eval: Reads to sample")
    p.add_argument("--seed", type=int, default=1336)
    p.add_argument("--since", default="", help="--redo/--eval window: 7d, 12h (default 7d, 30d for --eval)")
    p.add_argument("--root", default="", help="transcripts root (default $SOH_CLAUDE_PROJECTS or ~/.claude/projects)")
    p.add_argument("--live-home", action="store_true", help="--eval/--redo: run in the live home and write its "
                   "store; without it they run from a scratch home (DIR/home for --eval) #1346")
    p.set_defaults(func=cmd_spans)


def _since(a, default: str):
    import time

    from harness import context_report as cr
    return cr.parse_when(a.since or default, time.time())


def _root(a) -> Path:
    from harness import context_report as cr
    return Path(a.root).expanduser() if a.root else cr.default_root()


def cmd_spans(a) -> int:
    from harness import paths, spans
    if a.redo or a.eval:
        try:
            paths.eval_home(Path(a.eval).expanduser().resolve() / "home" if a.eval else None, live=a.live_home)
        except paths.LiveHomeRefused as exc:
            note(str(exc))
            emit(False, error=str(exc))
            return 2
        return _redo(a) if a.redo else _eval(a)
    if not a.path or not a.question.strip():
        note("give a path and -q QUESTION")
        emit(False, error="a path and a question")
        return 2
    from harness import completion
    try:
        got = spans.ask_file(a.path, a.question, lane=a.lane, cwd=Path.cwd(), max_tokens=a.max_tokens, model=a.model)
    except (ValueError, completion.CompletionError) as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 1
    note(got["text"])
    emit(**{k: v for k, v in got.items() if k != "text"})
    return 0


def _redo(a) -> int:
    from evals.importers import transcripts as tr
    from harness import spans
    try:
        since = _since(a, "7d")
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    streams = (list(tr.records(p)) for _project, main, subs in tr.sessions(_root(a)) for p in [main, *subs]
               if p.stat().st_mtime >= since)
    got = spans.redos(streams, since=since)
    rate = "--" if got["rate"] is None else f"{got['rate']:.0%}"
    note(f"{got['calls']} spans calls, {got['redos']} followed by a full Read within {spans.REDO_WINDOW} "
         f"tool calls ({rate}; the bar is 20%)")
    emit(**got)
    return 0


def _eval(a) -> int:
    from evals import spans_recall as sr
    from harness import spans
    try:
        since = _since(a, "30d")
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    found = [c for c in sr.cases(_root(a), since) if not a.kind or c.kind in a.kind]

    def answer(text, question):
        return spans.answer(text, question, lane=a.lane, max_tokens=a.max_tokens, model=a.model)

    def progress(r) -> None:
        note(f"{r['id']} {r['kind']:<8} {r['mode']:<5} {r['code'] or '-':<12} {r['found']}/{r['gold']} "
             f"{'ok' if r['verbatim'] else 'NOT VERBATIM'} {r['seconds']:.1f}s")
    got = sr.run(found, answer, Path(a.eval).expanduser().resolve(), n=a.n, seed=a.seed, progress=progress)
    recall = "--" if got["recall"] is None else f"{got['recall']:.0%}"
    note(f"{got['cases']} of {got['available']} Reads: spans {got['spans']}, whole {got['whole']} {got['whole_by']}; "
         f"recall {got['found']}/{got['gold']} ({recall}, bar {sr.RECALL_BAR:.0%}); verbatim "
         f"{got['verbatim']}/{got['cases']}; saved {got['saved_tokens']:,} of {got['read_tokens']:,} tokens; "
         f"{'passes' if got['passes'] else 'does not pass'}")
    emit(**got)
    return 0 if got["passes"] else 1
