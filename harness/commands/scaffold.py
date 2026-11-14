"""`soh scaffold module|knob|timeout|unit`: new code written with every registration make check asks of it (#1697)."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    p = sub.add_parser("scaffold", help="write a new module, knob, timeout constant or periodic unit together with "
                       "every registration the make check ratchets ask of it; then run make precheck")
    p.add_argument("--root", default="", help="the checkout to write into (default: this one)")
    p.add_argument("--issue", default="", help="the issue number the new lines cite")
    kinds = p.add_subparsers(dest="scaffold_kind")
    m = kinds.add_parser("module", help="a harness/ or evals/ module in its openspec capability")
    m.add_argument("path", help="harness/x.py or evals/x.py")
    m.add_argument("summary", help="the module's one-line docstring")
    m.add_argument("--capability", default="", help="its capability in openspec/capabilities.yaml (default: a sibling's)")
    m.add_argument("--command", action="store_true", help="also harness/commands/<name>.py, registered in harness/cli.py")
    k = kinds.add_parser("knob", help="register a gating site as a knob in an area of harness/knobs/")
    k.add_argument("name")
    k.add_argument("site", help="rel/path.py:NAME, as the inventory names it")
    k.add_argument("--values", required=True, help="comma-separated values to sweep, the current one included")
    k.add_argument("--note", required=True, help="what it limits, and why these values")
    k.add_argument("--unit", default="", help="s, tokens, GiB ...")
    k.add_argument("--area", default="", help="harness/knobs/<area>.py (default: the area that holds the file)")
    w = kinds.add_parser("not-gating", help="name why an inventory site gates no outcome, in its area's NOT_GATING")
    w.add_argument("site")
    w.add_argument("why")
    w.add_argument("--area", default="")
    t = kinds.add_parser("timeout", help="a module constant of seconds, registered as NOT_GATING (--why) or a knob")
    t.add_argument("path")
    t.add_argument("name", help="NAME_S or NAME_TIMEOUT")
    t.add_argument("seconds", type=float)
    t.add_argument("--why", default="", help="it gates no outcome, because ...")
    t.add_argument("--knob", default="", help="register as this knob; record its cut with cuts.timeout where it binds")
    t.add_argument("--values", default="", help="with --knob, other values to sweep")
    t.add_argument("--note", default="")
    t.add_argument("--area", default="")
    u = kinds.add_parser("unit", help="a periodic launchd unit: serve script, schedule, its hour knob, UNIT_OUTPUTS")
    u.add_argument("name")
    u.add_argument("command", help="what the unit runs, after `uv run`: soh x --y")
    u.add_argument("summary")
    u.add_argument("--hours", required=True, help="local hours, space separated: \"4\" or \"8 14\"")
    u.add_argument("--table", default="", help="the store table its runs write")
    u.add_argument("--time-col", default="", help="that table's time column")
    u.add_argument("--cond", default="", help="an SQL condition picking its rows out of the table")
    u.add_argument("--words", default="", help="comma-separated words a report names its output by (default: its name)")
    u.add_argument("--area", default="")
    u.add_argument("--every-machine", action="store_true", help="run on every role, not only the scheduler")
    p.set_defaults(func=cmd_scaffold)


def cmd_scaffold(a) -> int:
    from harness import knobs, scaffold
    root = Path(a.root) if a.root else knobs.REPO
    kind = a.scaffold_kind
    try:
        if kind == "module":
            done = scaffold.module(root, a.path, a.summary, capability=a.capability, issue=a.issue, command=a.command)
        elif kind == "knob":
            done = scaffold.scaffold_knob(root, a.name, a.site, a.values, a.note, unit=a.unit, area=a.area, issue=a.issue)
        elif kind == "not-gating":
            done = scaffold.scaffold_not_gating(root, a.site, a.why, area=a.area, issue=a.issue)
        elif kind == "timeout":
            done = scaffold.timeout(root, a.path, a.name, a.seconds, area=a.area, why=a.why, knob=a.knob,
                                    values=a.values, note=a.note, issue=a.issue)
            if a.knob:
                note(f"record its cut where it binds: with cuts.timeout({scaffold.q(a.knob)}, what): ...")
        elif kind == "unit":
            words = tuple(w.strip() for w in a.words.split(",") if w.strip())
            done = scaffold.unit(root, a.name, a.hours, a.command, a.summary, area=a.area, issue=a.issue,
                                 table=a.table, col=a.time_col, cond=a.cond, words=words,
                                 scheduler_only=not a.every_machine)
        else:
            note("soh scaffold module|knob|not-gating|timeout|unit; see soh scaffold -h")
            emit(False, error="no kind given")
            return 2
    except scaffold.ScaffoldError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    for rel in done:
        note(f"  wrote {rel}")
    note("then: make precheck")
    emit(written=done)
    return 0
