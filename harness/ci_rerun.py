"""Rerun once a check run whose check-macos hit its timeout on main, or was cancelled before any step ran on main or a PR. #1520, #1540."""
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


def started(job: dict) -> bool:
    """Whether any of the job's steps began; a job no runner picked up has none. #1540."""
    return any(s.get("started_at") for s in job.get("steps") or [])


def decide(run: dict, jobs: list[dict], tip: str, limit_min: float, reruns: int = RERUNS,
           repo: str = REPO, pr: int | None = None) -> tuple[bool, str]:
    """(rerun?, why) for one completed check run; `tip` is main's tip, or the open PR's head sha ("" when none)."""
    rid, event = run.get("id"), run.get("event")
    on_main = event == "push" and run.get("head_branch") == "main"
    if not on_main and event != "pull_request":
        return False, f"run {rid} is a {event} run on {run.get('head_branch')}, not a push to main or a pull request"
    if not on_main and (run.get("head_repository") or {}).get("full_name") != repo:
        return False, f"run {rid} is from a fork, not {repo}; a fork's run is never rerun automatically"
    # A job no runner picked up leaves its run concluded failure, not cancelled (#1540).
    if run.get("conclusion") not in ("cancelled", "failure"):
        return False, f"run {rid} concluded {run.get('conclusion')}; only a cancelled run is rerun, never a failure"
    job = next((j for j in jobs if j.get("name") == JOB), None)
    if job is None or job.get("conclusion") != "cancelled":
        got = job.get("conclusion") if job else "nothing"
        return False, f"run {rid}'s {JOB} concluded {got}, not cancelled" + ("; never a failure" if got == "failure" else "")
    attempt = int(run.get("run_attempt") or 1)
    if attempt > reruns:
        return False, f"run {rid} is on attempt {attempt}; it already had its {reruns} automatic rerun(s)"
    start, end = _ts(job.get("started_at")), _ts(job.get("completed_at"))
    used = (end - start) / 60 if start and end else 0.0
    ran = started(job)
    if ran and not on_main:
        return False, (f"run {rid}'s {JOB} was cancelled after {used:.1f} min with its steps started: its own timeout "
                       "or a newer push; a pull request run is rerun only when cancelled before any step ran")
    # A timed-out job runs its whole limit before its always() steps; anything shorter was a person or a newer push.
    if ran and used < limit_min:
        return False, (f"run {rid}'s {JOB} was cancelled after {used:.1f} of {limit_min:g} min: by a person or a newer "
                       "push, not its timeout")
    sha = run.get("head_sha", "")
    where = "main" if on_main else f"PR #{pr}'s head" if pr else "the PR's head"
    if not tip:
        return False, f"run {rid} is for {sha[:8]} on {run.get('head_branch')}, the head of no open PR"
    if sha != tip:
        return False, (f"run {rid} is for {sha[:8]} and {where} is now {tip[:8]}: the newer push's run covers it, "
                       "and a rerun would cancel it through the concurrency group")
    if not ran:
        return True, (f"run {rid}'s {JOB} was cancelled after {used:.1f} min before any step ran (no runner) on "
                      f"{where} {sha[:8]}; rerunning it once (attempt {attempt + 1})")
    return True, (f"run {rid}'s {JOB} hit its {limit_min:g} min timeout ({used:.1f} min) on main's tip {sha[:8]}; "
                  f"rerunning it once (attempt {attempt + 1})")


def head(run: dict, repo: str, gh) -> tuple[str, int | None]:
    """The sha a run must still match: main's tip, or the head and number of the open PR from its branch."""
    if run.get("event") != "pull_request":
        return gh(["api", f"repos/{repo}/commits/main", "-q", ".sha"]).strip(), None
    owner = ((run.get("head_repository") or {}).get("owner") or {}).get("login", "")
    got = json.loads(gh(["api", f"repos/{repo}/pulls?state=open&head={owner}:{run.get('head_branch', '')}"]) or "[]")
    return (got[0]["head"]["sha"], got[0]["number"]) if got else ("", None)


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
    tip, pr = head(run, a.repo, gh)
    ok, why = decide(run, jobs.get("jobs") or [], tip, limit_minutes(), repo=a.repo, pr=pr)
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
