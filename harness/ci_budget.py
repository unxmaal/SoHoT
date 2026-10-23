"""How much of its timeout-minutes a CI job has used; a GitHub warning past WARN_SHARE. #1146."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
WARN_SHARE = 0.8


def limit_minutes(job: str, workflow: Path = WORKFLOW) -> float:
    doc = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    jobs = doc.get("jobs") or {}
    if job not in jobs:
        raise KeyError(f"no job {job!r} in {workflow}")
    return float(jobs[job].get("timeout-minutes", 360))


def report(job: str, used_s: float, limit_min: float, share: float = WARN_SHARE) -> tuple[str, bool]:
    used = used_s / 60
    line = f"{job}: {used:.1f} of {limit_min:g} min ({used / limit_min:.0%} of its timeout)"
    return line, used > share * limit_min


def main(argv=None, environ=None, now=time.time) -> int:
    env = os.environ if environ is None else environ
    ap = argparse.ArgumentParser(prog="python -m harness.ci_budget", description=__doc__)
    ap.add_argument("--job", default=env.get("GITHUB_JOB", ""))
    ap.add_argument("--started", type=float, default=env.get("JOB_STARTED_S"),
                    help="epoch seconds the job's first step recorded")
    ap.add_argument("--workflow", type=Path, default=WORKFLOW)
    a = ap.parse_args(argv)
    if not a.job or a.started is None:
        print("needs --job and --started (or GITHUB_JOB and JOB_STARTED_S)", file=sys.stderr)
        return 2
    limit = limit_minutes(a.job, a.workflow)
    line, over = report(a.job, now() - float(a.started), limit)
    print(line)
    if over:
        print(f"::warning title=CI time::{line}; over {WARN_SHARE:.0%}, make the slow tests cheaper (#1146)")
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Job time\n\n{line}{' **over ' + format(WARN_SHARE, '.0%') + '**' if over else ''}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
