"""`soh route-trial`: run a lane's alias and both routing arms paired on one exam, and judge the adaptive arm. #1338."""
from __future__ import annotations

import subprocess
import sys

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    from harness import routes
    p = sub.add_parser("route-trial", help="routing trial: the lane alias against the heuristic and adaptive "
                       "LiteLLM routers over it and the cloud alias, paired per case (#1338)")
    p.add_argument("action", choices=("run", "report", "command"),
                   help="run: evals.run the arms then report; report: a stored run; command: print the evals.run line")
    p.add_argument("--lane", required=True, choices=routes.LANES)
    p.add_argument("--split", choices=("all", "dev", "holdout"), default="holdout",
                   help="holdout for the final call; dev to look")
    p.add_argument("--repeat", type=int, default=None)
    p.add_argument("--with", dest="extra", action="append", default=[], metavar="CANDIDATE",
                   help="another candidate to run beside the arms, e.g. cloud-opus as the all-cloud policy")
    p.add_argument("--run", dest="run_id", type=int, default=None, help="report: the stored run (default newest)")
    p.set_defaults(func=cmd_route_trial)


def argv(lane: str, split: str = "holdout", repeat: int | None = None, extra=()) -> list[str]:
    from harness import routes
    out = ["-m", "evals.run", "--modality", lane, "--candidates", ",".join(routes.arms_of(lane) + list(extra)),
           "--split", split]
    return out + (["--repeat", str(repeat)] if repeat else [])


def lines(got: dict) -> list[str]:
    out = [f"run {got['run']}  lane {got['lane']}  split {got['split']}"
           + ("" if got["split"] == "holdout" else "  (not the holdout: no final call)"),
           f"{'arm':<26} {'pass':>9} {'rate':>6} {'cut':>4} {'cloud':>6} {'cloud tok':>10} {'wall s':>8}"]
    for a in got["arms"]:
        rate = "--" if a["rate"] is None else f"{a['rate']:.1%}"
        out.append(f"{a['candidate']:<26} {a['passed']:>4}/{a['judged']:<4} {rate:>6} {a['cut']:>4} "
                   f"{a['cloud_calls']:>6} {a['cloud_tokens']:>10} {a['wall_s']:>8}")
    for v in got["verdicts"]:
        out.append(f"{v['challenger']} vs {v['base']}: {'ADOPT' if v['adopt'] else 'keep ' + v['base']} "
                   f"({v['gained']} gained, {v['lost']} lost of {v['paired']}, p={v['p']:.3f}, "
                   f"pass drop {v['drop']:+.1%} against effect {v['effect']:.0%}): {v['why']}")
    if not got["verdicts"]:
        out.append("the adaptive arm did not run, so there is nothing to judge")
    return out


def cmd_route_trial(a) -> int:
    from harness import routes
    from harness import memory_store as ms
    if a.action == "command":
        cmd = " ".join(["uv run python", *argv(a.lane, a.split, a.repeat, a.extra)])
        note(cmd)
        emit(command=cmd)
        return 0
    if a.action == "run":
        rc = subprocess.call([sys.executable, *argv(a.lane, a.split, a.repeat, a.extra)])
        if rc:
            note(f"evals.run exited {rc}")
            emit(False, error=f"evals.run exited {rc}")
            return rc
    conn = ms.connect()
    try:
        run_id = a.run_id or routes.latest_run(conn, a.lane)
        if run_id is None:
            note(f"no stored run of {routes.alias(a.lane, routes.ADAPTIVE)}; `soh route-trial run --lane {a.lane}`")
            emit(False, error="no trial run")
            return 1
        got = routes.trial(conn, run_id, a.lane)
    finally:
        conn.close()
    for line in lines(got):
        note(line)
    emit(**got)
    return 0
