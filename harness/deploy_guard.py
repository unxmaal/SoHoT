"""Deploy only a main commit whose own push run of check-macos passed. #870.

scripts/launchd.sh deploy runs this as a file with the commit it is about to check out, so it
imports nothing outside the stdlib. Exit 0 lets the deploy go ahead; anything else refuses it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

WORKFLOW = "ci.yml"
JOB = "check-macos"
OVERRIDE = "LH_DEPLOY_UNCHECKED"
GH_TIMEOUT_S = 60.0
OK, REFUSED = 0, 1


class GhError(RuntimeError):
    pass


def _gh(argv: list[str], cwd: str | None = None) -> str:
    try:
        got = subprocess.run(["gh", *argv], cwd=cwd, capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    except FileNotFoundError as exc:
        raise GhError("gh is not installed or not on PATH") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise GhError(f"gh {argv[0]} {argv[1]} did not run: {exc}") from exc
    if got.returncode != 0:
        why = (got.stderr or got.stdout or "").strip()[:300]
        raise GhError(f"gh {argv[0]} {argv[1]} failed (rc {got.returncode}): {why}. Is `gh auth status` logged in?")
    return got.stdout


def verdict(sha: str, gh=_gh) -> tuple[bool, str]:
    """(deployable, why) for `sha`, from the push runs of WORKFLOW on main whose headSha is `sha`."""
    try:
        runs = json.loads(gh(["run", "list", "--workflow", WORKFLOW, "--branch", "main", "--event", "push",
                              "--commit", sha, "--json", "databaseId,conclusion,headSha,status,url"]) or "[]")
        runs = [r for r in runs if r.get("headSha") == sha]
        if not runs:
            return False, (f"no push run of {WORKFLOW} on main for {sha[:12]}; GitHub may not have started it yet. "
                           f"Check with: gh run list --workflow {WORKFLOW} --branch main --commit {sha}")
        waiting = []
        failed = []
        for run in runs:
            url = run.get("url", "")
            if run.get("status") != "completed":
                waiting.append(run)
                continue
            jobs = json.loads(gh(["run", "view", str(run["databaseId"]), "--json", "jobs"]) or "{}").get("jobs") or []
            job = next((j for j in jobs if j.get("name") == JOB), None)
            if job is None:
                failed.append(f"run {url} has no {JOB} job")
            elif job.get("conclusion") == "success":
                return True, f"{JOB} passed for {sha[:12]} in {url}"
            else:
                failed.append(f"{JOB} concluded {job.get('conclusion') or 'nothing'} in {url}")
    except GhError as exc:
        return False, f"cannot ask GitHub whether {sha[:12]} passed {JOB}: {exc}"
    except (ValueError, KeyError, TypeError) as exc:
        return False, f"gh answered something unreadable for {sha[:12]}: {exc}"
    if waiting:
        run = waiting[0]
        return False, (f"{JOB} for {sha[:12]} is still {run.get('status') or 'running'}: {run.get('url', '')}. "
                       f"Wait for it with: gh run watch {run.get('databaseId')} --exit-status, then re-run install")
    return False, f"{JOB} did not pass for {sha[:12]}: " + "; ".join(failed)


def check(sha: str, environ=None, gh=_gh, err=None) -> int:
    """Print the verdict on stderr and return the exit status; OVERRIDE=1 deploys anyway, loudly."""
    environ = os.environ if environ is None else environ
    err = sys.stderr if err is None else err
    if environ.get(OVERRIDE) == "1":
        print(f"WARNING: {OVERRIDE}=1, deploying {sha[:12]} WITHOUT checking that {JOB} passed for it", file=err)
        return OK
    ok, why = verdict(sha, gh=gh)
    if ok:
        print(f"deploy guard: {why}", file=err)
        return OK
    print(f"REFUSING to deploy: {why}", file=err)
    print(f"To deploy it anyway, deliberately: {OVERRIDE}=1 ./scripts/launchd.sh install", file=err)
    return REFUSED


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print("usage: deploy_guard.py SHA [REPO_DIR]", file=sys.stderr)
        return 2
    cwd = argv[1] if len(argv) == 2 else None
    return check(argv[0], gh=lambda a: _gh(a, cwd=cwd))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
