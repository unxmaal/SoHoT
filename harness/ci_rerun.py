"""Rerun once a push-to-main check run whose check-macos hit its job timeout, so runner variance does not block a deploy. #1520."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

REPO = "unxmaal/SoHoT"
JOB = "check-macos"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
#: How many automatic reruns one push run of check-macos gets; attempt RERUNS + 1 is never rerun. #1520.
RERUNS = 1


def _ts(s: str | None) -> float | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def limit_minutes(workflow: Path = WORKFLOW, job: str = JOB) -> float:
    doc = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    return float(doc["jobs"][job].get("timeout-minutes", 360))


def decide(run: dict, jobs: list[dict], tip: str, limit_min: float, reruns: int = RERUNS) -> tuple[bool, str]:
    """(rerun?, why) for one completed run of the check workflow."""
    rid = run.get("id")
    if run.get("event") != "push" or run.get("head_branch") != "main":
        return False, f"run {rid} is a {run.get('event')} run on {run.get('head_branch')}, not a push to main"
    if run.get("conclusion") != "cancelled":
        return False, f"run {rid} concluded {run.get('conclusion')}; only a cancelled run is rerun, never a failure"
    attempt = int(run.get("run_attempt") or 1)
    if attempt > reruns:
        return False, f"run {rid} is on attempt {attempt}; it already had its {reruns} automatic rerun(s)"
    sha = run.get("head_sha", "")
    if sha != tip:
        return False, (f"run {rid} is for {sha[:8]} and main is now {tip[:8]}: the newer push's run covers main, "
                       "and a rerun would cancel it through the concurrency group")
    job = next((j for j in jobs if j.get("name") == JOB), None)
    if job is None or job.get("conclusion") != "cancelled":
        return False, f"run {rid}'s {JOB} concluded {job.get('conclusion') if job else 'nothing'}, not cancelled"
    start, end = _ts(job.get("started_at")), _ts(job.get("completed_at"))
    used = (end - start) / 60 if start and end else 0.0
    # A timed-out job runs its whole limit before its always() steps; anything shorter was a person or a newer push.
    if used < limit_min:
        return False, (f"run {rid}'s {JOB} was cancelled after {used:.1f} of {limit_min:g} min: by a person or a newer "
                       "push, not its timeout")
    return True, (f"run {rid}'s {JOB} hit its {limit_min:g} min timeout ({used:.1f} min) on main's tip {sha[:8]}; "
                  f"rerunning it once (attempt {attempt + 1})")


def _gh(argv: list[str]) -> str:
    got = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=120)
    if got.returncode != 0:
        raise RuntimeError(f"gh {' '.join(argv[:3])} failed: {(got.stderr or got.stdout).strip()[:300]}")
    return got.stdout


def main(argv=None, gh=_gh, environ=None) -> int:
    env = os.environ if environ is None else environ
    ap = argparse.ArgumentParser(prog="python harness/ci_rerun.py", description=__doc__)
    ap.add_argument("run_id")
    ap.add_argument("--repo", default=env.get("GITHUB_REPOSITORY") or REPO)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    run = json.loads(gh(["api", f"repos/{a.repo}/actions/runs/{a.run_id}"]))
    attempt = run.get("run_attempt") or 1
    jobs = json.loads(gh(["api", f"repos/{a.repo}/actions/runs/{a.run_id}/attempts/{attempt}/jobs?per_page=100"]))
    tip = gh(["api", f"repos/{a.repo}/commits/main", "-q", ".sha"]).strip()
    ok, why = decide(run, jobs.get("jobs") or [], tip, limit_minutes())
    print(why)
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Rerun of a cancelled check-macos\n\n{why}\n")
    if ok and not a.dry_run:
        gh(["run", "rerun", str(a.run_id), "-R", a.repo])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
