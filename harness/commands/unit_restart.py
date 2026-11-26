"""`soh unit-restart NAME`: restart one launchd unit through scripts/launchd.sh restart, never unload (#2134)."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("unit-restart", help="restart one launchd unit through scripts/launchd.sh restart, the path the "
                       "watchdog and gateway switch use; never unload")
    p.add_argument("name", help="a unit scripts/launchd.sh installs, e.g. gateway")
    p.set_defaults(func=cmd_unit_restart)


def cmd_unit_restart(a) -> int:
    from harness import unit_restart
    got = unit_restart.restart(a.name)
    (note if got["rc"] == 0 else err)(got["line"])
    emit(**got)
    return 0 if got["rc"] == 0 else 1
