"""Deploy only a main commit whose own push run of check-macos passed, or whose tree a passed PR run tested. #870, #1684.

scripts/launchd.sh deploy runs this as a file with the commit it is about to check out, so it
imports nothing outside the stdlib. Exit 0 lets the deploy go ahead; anything else refuses it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

WORKFLOW = "ci.yml"
JOB = "check-macos"
OVERRIDE = "LH_DEPLOY_UNCHECKED"
GH_TIMEOUT_S = 60.0
OK, REFUSED = 0, 1
PASSED, FAILED, CANCELLED, WAITING, NONE = "passed", "failed", "cancelled", "waiting", "none"
#: How judge() accepted a sha: main's own push run, or a passed PR run on the same tree (#1684).
BY_MAIN, BY_PR = "main", "pr"
_PR = re.compile(r"\(#(\d+)\)\s*$|^Merge pull request #(\d+)")


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


def _git(argv: list[str], repo=None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *(["-C", str(repo)] if repo else []), *argv], capture_output=True, text=True,
                              timeout=GH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GhError(f"git {argv[0]} did not run: {exc}") from exc


def _scan(sha: str, argv: list[str], gh, what: str) -> tuple[str, str]:
    """(state, why) of the check-macos job over the runs `gh run list argv` names for head `sha`."""
    runs = [r for r in json.loads(gh(argv) or "[]") if r.get("headSha") == sha]
    if not runs:
        return NONE, (f"no {what} run of {WORKFLOW} for {sha[:12]}; GitHub may not have started it yet. "
                      f"Check with: gh run list --workflow {WORKFLOW} --commit {sha}")
    waiting, failed = [], []
    for run in runs:
        url = run.get("url", "")
        jobs = json.loads(gh(["run", "view", str(run["databaseId"]), "--json", "jobs"]) or "{}").get("jobs") or []
        job = next((j for j in jobs if j.get("name") == JOB), None)
        if job is not None and job.get("conclusion") == "success":
            return PASSED, f"{JOB} passed for {sha[:12]} in {url}"
        if run.get("status") != "completed":
            # The run's other jobs (check-postgres) may still be queued for a runner; only check-macos gates (#1802).
            waiting.append(run)
            continue
        if job is None:
            failed.append((None, f"run {url} has no {JOB} job"))
        else:
            failed.append((job.get("conclusion"), f"{JOB} concluded {job.get('conclusion') or 'nothing'} in {url}"))
    if waiting:
        run = waiting[0]
        return WAITING, (f"{JOB} for {sha[:12]} is still {run.get('status') or 'running'}: {run.get('url', '')}. "
                         f"Wait for it with: gh run watch {run.get('databaseId')} --exit-status, then re-run install")
    state = CANCELLED if all(c == "cancelled" for c, _ in failed) else FAILED
    return state, f"{JOB} did not pass for {sha[:12]}: " + "; ".join(w for _, w in failed)


def own(sha: str, gh=_gh) -> tuple[str, str]:
    """(state, why) of `sha`'s own push run on main; raises GhError, or ValueError on an unreadable answer."""
    return _scan(sha, ["run", "list", "--workflow", WORKFLOW, "--branch", "main", "--event", "push",
                       "--commit", sha, "--json", "databaseId,conclusion,headSha,status,url"], gh, "push")


def twin(sha: str, gh=_gh, repo=None, git=_git) -> tuple[bool, str]:
    """(ok, why): the PR sha's subject names has a head with sha's tree, holding sha's parent, whose PR run passed."""
    def out(*argv: str) -> str:
        got = git(list(argv), repo)
        if got.returncode != 0:
            raise GhError(f"git {argv[0]} failed: {(got.stderr or got.stdout).strip()[:200]}")
        return got.stdout.strip()
    subject, _, parents = out("log", "-1", "--format=%s%n%P", sha).partition("\n")
    m = _PR.search(subject)
    if not m:
        return False, f"its subject names no pull request: {subject[:80]!r}"
    pr = m.group(1) or m.group(2)
    out("fetch", "-q", "--no-tags", "origin", f"refs/pull/{pr}/head")
    head = out("rev-parse", "FETCH_HEAD^{commit}")
    if out("rev-parse", f"{head}^{{tree}}") != out("rev-parse", f"{sha}^{{tree}}"):
        return False, f"PR #{pr} head {head[:12]} has a different tree from {sha[:12]}"
    parent = parents.split()[0] if parents.split() else ""
    if parent and git(["merge-base", "--is-ancestor", parent, head], repo).returncode != 0:
        return False, f"PR #{pr} head {head[:12]} lacks main's {parent[:12]}, so its run tested another merge"
    state, why = _scan(head, ["run", "list", "--workflow", WORKFLOW, "--event", "pull_request", "--commit", head,
                              "--json", "databaseId,conclusion,headSha,status,url"], gh, "pull_request")
    if state != PASSED:
        return False, f"PR #{pr} head {head[:12]} has {sha[:12]}'s tree but {why}"
    return True, f"PR #{pr} head {head[:12]} has the same tree as {sha[:12]} and {why}"


def judge(sha: str, gh=_gh, repo=None, git=_git) -> tuple[bool, str, str]:
    """(deployable, why, BY_MAIN or BY_PR or '') for `sha`; main's own concluded run outranks any PR run."""
    try:
        state, why = own(sha, gh)
        if state == PASSED:
            return True, why, BY_MAIN
        if state not in (WAITING, NONE):
            return False, why, ""
    except GhError as exc:
        return False, f"cannot ask GitHub whether {sha[:12]} passed {JOB}: {exc}", ""
    except (ValueError, KeyError, TypeError) as exc:
        return False, f"gh answered something unreadable for {sha[:12]}: {exc}", ""
    try:
        ok, said = twin(sha, gh, repo, git)
    except (GhError, ValueError, KeyError, TypeError) as exc:
        ok, said = False, f"no passed PR run on the same tree: {exc}"
    return (True, f"{said}; main's own run is {state}", BY_PR) if ok else (False, f"{why}; and {said}", "")


def verdict(sha: str, gh=_gh, repo=None, git=_git) -> tuple[bool, str]:
    """(deployable, why) for `sha`."""
    ok, why, _ = judge(sha, gh, repo, git)
    return ok, why


def check(sha: str, environ=None, gh=_gh, err=None, repo=None, git=_git) -> int:
    """Print the verdict on stderr and return the exit status; OVERRIDE=1 deploys anyway, loudly."""
    environ = os.environ if environ is None else environ
    err = sys.stderr if err is None else err
    if environ.get(OVERRIDE) == "1":
        print(f"WARNING: {OVERRIDE}=1, deploying {sha[:12]} WITHOUT checking that {JOB} passed for it", file=err)
        return OK
    ok, why = verdict(sha, gh, repo, git)
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
    return check(argv[0], gh=lambda a: _gh(a, cwd=cwd), repo=cwd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
