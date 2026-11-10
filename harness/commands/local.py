"""`soh local complete|decide`: local_complete and local_decide without an MCP connection, recorded the same way. #1687."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from harness.commands.common import emit, note

JSON_HELP = "machine-readable result on stdout, including on failure"


def add_parser(sub) -> None:
    p = sub.add_parser("local", help="local_complete / local_decide from the shell when the soh MCP server is not "
                       "connected; records the delegation and prints its call_id for `soh delegated`")
    verbs = p.add_subparsers(dest="local_verb")
    c = verbs.add_parser("complete", help="a text subtask on a lane's adopted local model, as local_complete")
    c.add_argument("prompt", nargs="?", default="", help="the task; omit to read stdin (or pass --paths)")
    c.add_argument("--lane", default="", help="code, web, svg, extract or decide (default code; extract with --paths)")
    c.add_argument("--system", default=None, help="replaces the lane's own system prompt")
    c.add_argument("--max-tokens", type=int, default=None)
    c.add_argument("--temperature", type=float, default=None)
    c.add_argument("--thinking", choices=("on", "off"), default=None, help="a hybrid model's reasoning")
    c.add_argument("--paths", nargs="+", default=None, help="files the server reads itself, as local_complete paths")
    c.add_argument("-q", "--question", default="", help="what to find in --paths")
    c.add_argument("--mode", choices=("", "spans"), default="", help="spans: the lines of one file that answer -q")
    c.add_argument("--json", action="store_true", help=JSON_HELP)
    c.set_defaults(func=cmd_complete)
    d = verbs.add_parser("decide", help="classify with the decide lane's adopted model, as local_decide")
    d.add_argument("question")
    d.add_argument("--schema", required=True, help="a JSON file or inline JSON: {field: {type: enum|boolean, "
                   "description, choices}}")
    d.add_argument("--context", default=None, help="the material to judge; -f FILE or stdin otherwise")
    d.add_argument("-f", "--file", default="", help="read the material from FILE")
    d.add_argument("--json", action="store_true", help=JSON_HELP)
    d.set_defaults(func=cmd_decide)
    p.set_defaults(func=lambda a: _usage(p))


def _usage(p) -> int:
    p.print_help(sys.stderr)
    return 2


def _stdin() -> str:
    return "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()


def _failed(exc: Exception) -> int:
    note(str(exc))
    emit(False, error=str(exc))
    return 1


def _done(got: dict, answer: str) -> int:
    from harness import delegations
    got["report"] = delegations.instruction(got["call_id"], cli=True)
    note(answer)
    note(f"-- {got.get('model', '')}, {got.get('seconds') or 0:.1f}s, call_id {got['call_id']}")
    note(got["report"])
    emit(**got)
    return 0


def cmd_complete(a) -> int:
    from harness import completion, local_tools
    prompt = a.prompt or ("" if a.paths else _stdin())
    if not prompt.strip() and not (a.paths and a.question.strip()):
        return _failed(ValueError("give a prompt (or stdin), or --paths with -q QUESTION"))
    try:
        got = local_tools.complete(prompt, a.lane, a.system, max_tokens=a.max_tokens, temperature=a.temperature,
                                   thinking=None if a.thinking is None else a.thinking == "on", paths=a.paths,
                                   question=a.question, mode=a.mode, cwd=Path.cwd())
    except (ValueError, completion.CompletionError) as exc:
        return _failed(exc)
    return _done(got, got.get("text") or "")


def cmd_decide(a) -> int:
    from harness import completion, local_tools
    try:
        raw = a.schema if a.schema.lstrip().startswith("{") else Path(a.schema).read_text(encoding="utf-8")
        schema = json.loads(raw)
        context = a.context if a.context is not None else (
            Path(a.file).read_text(encoding="utf-8") if a.file else _stdin())
        got = local_tools.decide(a.question, schema, context=context)
    except (OSError, ValueError, completion.CompletionError) as exc:
        return _failed(exc)
    return _done(got, json.dumps(got.get("answers") or {}, sort_keys=True))
