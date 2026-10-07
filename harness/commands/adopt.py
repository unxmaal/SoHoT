"""`soh adopt`: make a measured run a lane's winner."""
from __future__ import annotations

from pathlib import Path

from harness import lanes, paths
from harness.commands.common import err
from harness.commands import measure as measure_cmd


def _run_name(run: Path) -> str:
    """A run under the runs dir by its directory name, anything else by path."""
    try:
        return str(run.resolve().relative_to((paths.home() / "runs").resolve()))
    except ValueError:
        return str(run)


def cmd_adopt(a) -> int:
    """The discovery loop's paired measure-and-adopt, for a named challenger."""
    lane = lanes.canonical(a.lane)
    if lane not in lanes.ALL:
        return err(f"unknown lane {a.lane!r}; known: {', '.join(lanes.ALL)}")
    return measure_cmd._measure_and_adopt(a, {"name": a.challenger, "lane": lane})
