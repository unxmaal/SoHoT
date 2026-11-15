"""`soh tool-route`: oversized Bash and Read results handed to the local lanes by a PostToolUse hook (#2032)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from harness.commands.common import emit, note

def add_parser(sub) -> None:
    p = sub.add_parser("tool-route", help="replace a Bash or whole-file Read result over --chars with its local "
                       "digest or spans, the raw output kept under the worktree's tmp/tool-route")
    how = p.add_mutually_exclusive_group(required=True)
    how.add_argument("--hook", action="store_true", help="read a PostToolUse event on stdin and print the "
                     "replacement, or nothing to leave the result whole")
    how.add_argument("--settings", action="store_true", help="print the settings.json block that runs the hook")
    how.add_argument("--install", metavar="SETTINGS", default="", help="merge that block into this settings.json")
    p.add_argument("--chars", type=int, default=None, help="route results of at least this many characters "
                   "(default: knob tool_route_chars)")
    p.set_defaults(func=cmd_tool_route)


def command(chars: int, timeout: int) -> str:
    from harness import paths, tool_route
    where = paths.deploy_link() or paths.REPO
    return f"python3 {Path(where) / 'scripts' / tool_route.SCRIPT} {chars} {timeout}"


def _hook(tr, chars: int, stdin) -> int:
    """Claude Code's hook protocol, not a verb result: the replacement JSON on stdout, or nothing."""
    try:
        got = tr.hook(json.loads((stdin or sys.stdin).read() or "{}"), chars)
    except Exception:  # noqa: BLE001 - a hook that fails shows the result whole
        got = None
    if got:
        sys.stdout.write(json.dumps(got) + "\n")
    return 0


def cmd_tool_route(a, stdin=None) -> int:
    from harness import monitor
    from harness import tool_route as tr
    chars = a.chars or tr.CHARS
    if a.hook:
        return _hook(tr, chars, stdin)
    block = tr.settings(command(chars, tr.TIMEOUT_S - 10), tr.TIMEOUT_S)
    if a.settings:
        note("add to ~/.claude/settings.json or a project's .claude/settings.json (not applied here):")
        note(json.dumps(block, indent=2))
        emit(settings=block)
        return 0
    target = Path(a.install).expanduser()
    if not monitor.live_home():
        note(monitor.off_live(f"--install, which writes {target} that every Claude Code session reads,"))
        emit(ok=False, error="not the live home", settings=block)
        return 1
    try:
        did = tr.install(target, block)
    except RuntimeError as e:
        note(str(e))
        emit(ok=False, error=str(e), settings=block)
        return 1
    note({"added": "added the hook to ", "replaced": "replaced the older tool-route hook in ",
          "present": "the hook is already in "}[did] + str(target))
    emit(installed=did, settings=block)
    return 0
