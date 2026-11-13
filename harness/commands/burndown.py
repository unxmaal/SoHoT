"""`soh burndown`: issues opened, closed and open per day or week, and open issues by age and label, from gh. #1685."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("burndown", help="issues opened, closed, net and open at each boundary per week (or per day "
                       "with --days), and open issues by age and by label")
    p.add_argument("--weeks", type=int, default=8, help="weeks to show (default 8)")
    p.add_argument("--days", type=int, default=0, help="show this many days, one row a day, instead of weeks")
    p.set_defaults(func=cmd_burndown)


def cmd_burndown(a) -> int:
    from harness import burndown
    try:
        got = burndown.collect(a.days or a.weeks, 1 if a.days else 7)
    except RuntimeError as exc:
        return err(str(exc))
    note(burndown.render(got))
    emit(**got)
    return 0
