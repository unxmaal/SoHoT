"""`soh ci-times`: CI, merge and deploy latency per merged PR and per CI job against its timeout, from gh. #1685."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("ci-times", help="per merged PR: open->merge, check-macos and CI wall time on its final run, "
                       "CI rounds, main's own check after merge and merge->deploy; per ci.yml job: p50/p95 minutes "
                       "against its timeout")
    p.add_argument("--last", type=int, default=20, help="newest merged PRs to show (default 20)")
    p.add_argument("--runs", type=int, default=30, help="newest completed ci.yml runs for the job table (default 30)")
    p.set_defaults(func=cmd_ci_times)


def cmd_ci_times(a) -> int:
    from harness import ci_times, paths
    try:
        got = ci_times.collect(a.last, a.runs, paths.home())
    except (RuntimeError, OSError) as exc:
        return err(str(exc))
    note(ci_times.render(got))
    emit(**got)
    return 0
