"""`soh unverified`: the Stop hook that flags final-message claims no tool result in the turn supports. #1380."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("unverified", help="Stop hook: flag claims in the final message that no tool result in "
                       "the turn supports (--hook reads the hook's stdin; --settings prints the block to add)")
    how = p.add_mutually_exclusive_group(required=True)
    how.add_argument("--hook", action="store_true", help="read a Stop hook event on stdin and print its verdict")
    how.add_argument("--transcript", default="", help="check the last turn of this transcript; writes nothing")
    how.add_argument("--settings", action="store_true", help="print the settings.json block that turns it on")
    p.set_defaults(func=cmd_unverified)


def _command() -> str:
    from harness import paths
    where = paths.deploy_checkout()
    return f"uv run --quiet --project {where or '<deploy checkout>'} soh unverified --hook"


def _answer_hook(stdin, decide) -> int:
    """Claude Code reads the hook's stdout as its verdict, so it is the block object or nothing, whatever --json says."""
    from harness import unverified as uv
    try:
        event = json.loads(stdin.read() or "{}")
    except ValueError:
        event = {}
    row = uv.hook(event if isinstance(event, dict) else {}, decide)
    if row["decision"] == uv.BLOCK:
        print(json.dumps({"decision": "block", "reason": uv.reason(row["flagged"])}))
    return 0


def cmd_unverified(a, decide=None, stdin=None) -> int:
    from harness import unverified as uv
    if a.settings:
        block = uv.settings(_command())
        note("add to the project's .claude/settings.json (not applied here):")
        note(json.dumps(block, indent=2))
        emit(settings=block)
        return 0
    if a.hook:
        return _answer_hook(stdin or sys.stdin, decide)
    path = Path(a.transcript).expanduser()
    if not path.is_file():
        return err(f"no transcript at {path}")
    got = uv.turn_of(path)
    if got is None:
        return err("the last turn starts before the transcript bytes the hook reads (unverified_transcript_bytes)")
    started = time.monotonic()
    turn_id, turn = got
    row = uv.check(uv.final_text(turn), turn, decide)
    row["seconds"] = round(time.monotonic() - started, 3)
    note(f"{row['decision']} ({row['why']}): {row['candidates']} candidates, {row['checked']} checked, "
         f"{len(row['flagged'])} flagged, {row['seconds']} s")
    for c in row["flagged"]:
        note(f"  {c}")
    emit(**row)
    return 0
