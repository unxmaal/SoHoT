"""The local merge gate: test a pull request's head merged onto main in a clean worktree and post the verdict as a commit status (#2110)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from harness import deploy_guard as guard
from harness import paths

STEP_TIMEOUT_S = 3600.0
CONTEXT = guard.GATE
#: Who a queued pass says asked for it; one waits or runs at a time.
REQUESTER = "merge-gate"
PENDING, SUCCESS, FAILURE, ERROR = "pending", "success", "failure", "error"
#: A verdict on a tree that stands until the tree changes; a pending or errored one is tested again.
FINAL = (SUCCESS, FAILURE)
#: GitHub cuts a status description here.
DESCRIPTION_MAX = 140
#: The suite's xdist workers on a machine that is doing other work. #1722
MAKE = ("make", "PYTEST_N=6")
TIMED_OUT = 124
_SEAM = re.compile(r"^\s*seam='(.+)'\s*$", re.M)


class GateError(RuntimeError):
    pass


def root() -> Path:
    d = paths.home() / "merge-gate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _out(repo, *argv: str) -> str:
    got = guard._git(list(argv), repo)
    if got.returncode != 0:
        raise GateError(f"git {' '.join(argv[:2])} failed: {(got.stderr or got.stdout).strip()[:200]}")
    return got.stdout.strip()


def candidates(gh) -> list[dict]:
    """Open pull requests on main to test: not a draft, and from this repository, so a fork's code never runs here."""
    rows = json.loads(gh(["pr", "list", "--state", "open", "--base", "main", "--limit", "200",
                          "--json", "number,headRefOid,isCrossRepository,isDraft"]) or "[]")
    return [r for r in rows if r.get("isCrossRepository") is False and r.get("isDraft") is False]


def merged(repo, base: str, head: str) -> str:
    """The tree of `head` merged onto `base`; '' when they conflict."""
    got = guard._git(["merge-tree", "--write-tree", base, head], repo)
    if got.returncode not in (0, 1):
        raise GateError(f"git merge-tree failed: {(got.stderr or got.stdout).strip()[:200]}")
    return got.stdout.split()[0] if got.returncode == 0 else ""


def verdict(head: str, key: str, gh) -> str:
    """The state of the newest gate status on `head` when it names `key`; '' when it names another tree or there is none."""
    for s in json.loads(gh(["api", f"repos/{{owner}}/{{repo}}/commits/{head}/statuses?per_page=100"]) or "[]"):
        if s.get("context") == CONTEXT:
            return (s.get("state") or "") if (s.get("description") or "").startswith(f"{key} ") else ""
    return ""


def post(head: str, state: str, text: str, gh) -> None:
    gh(["api", "-X", "POST", f"repos/{{owner}}/{{repo}}/statuses/{head}", "-f", f"state={state}",
        "-f", f"context={CONTEXT}", "-f", f"description={text[:DESCRIPTION_MAX]}"])


def plan(repo, pr: dict | None, gh) -> dict:
    """What testing `pr` (None: main's own tip) tests now: head, base, the merged tree, and whether that tree has its verdict."""
    _out(repo, "fetch", "-q", "--no-tags", "origin", "main")
    main = _out(repo, "rev-parse", "FETCH_HEAD^{commit}")
    if pr is None:
        tree = _out(repo, "rev-parse", f"{main}^{{tree}}")
        state = {guard.PASSED: SUCCESS, guard.FAILED: FAILURE}.get(guard.gated(main, gh, repo)[0], "")
        return {"pr": None, "head": main, "base": _out(repo, "rev-parse", f"{main}^"), "tree": tree,
                "key": guard.stamp(tree), "state": state}
    head = pr["headRefOid"]
    _out(repo, "fetch", "-q", "--no-tags", "origin", f"refs/pull/{pr['number']}/head")
    tree = merged(repo, main, head)
    key = guard.stamp(tree) if tree else f"conflict {main}"
    return {"pr": pr, "head": head, "base": main, "tree": tree, "key": key, "state": verdict(head, key, gh)}


def _env(home: Path) -> dict:
    """The suite's environment: CI's SQLite store on a scratch home, and nothing of the queue job that runs it."""
    from harness import store
    from harness import workqueue as wq
    drop = (wq.JOB_ENV, wq.ITEM_ENV, "VIRTUAL_ENV", paths.MACHINE_ENV, paths.MACHINE_FOR_ENV, paths.MACHINE_STORE_ENV)
    return {**{k: v for k, v in os.environ.items() if k not in drop},
            paths.ENV_VAR: str(home), store.BACKEND_ENV: "sqlite"}


def _run(argv: list[str], cwd: Path, env: dict, capture: bool = False) -> tuple[int, str]:
    from harness import cuts
    try:
        with cuts.timeout("merge_gate_step_timeout", " ".join(argv[:3])):
            got = subprocess.run(argv, cwd=str(cwd), env=env, timeout=STEP_TIMEOUT_S, text=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else None)
    except subprocess.TimeoutExpired:
        return TIMED_OUT, ""
    return got.returncode, got.stdout or ""


def suite(work: Path, base: str, home: Path, run=None) -> str:
    """'' when the suite, the Postgres suite a store change needs and the changed functions' mutation run pass in `work`; else the step that did not."""
    env = _env(home)
    def go(argv, capture=False):
        return (run or _run)(list(argv), work, env, capture)
    if go([*MAKE, "check"])[0]:
        return "make check"
    changed = _out(work, "diff", "--name-only", f"{base}...HEAD").splitlines()
    seam = _SEAM.search((work / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    if seam is None or any(re.search(seam.group(1), f) for f in changed):
        if go([*MAKE, "test-postgres"])[0]:
            return "make test-postgres"
    rc, listed = go(["uv", "run", "python", "-m", "tests.gauntlet.mutation", "changed", "--base", base], capture=True)
    if rc:
        return "the mutation plan"
    for line in listed.splitlines():
        module, _, fns = line.partition("\t")
        if not module.strip():
            continue
        args = " ".join(["--module", module.strip(), *(w for f in fns.split() for w in ("--function", f))])
        if go(["make", "mutation", f"MUTATION_ARGS={args}"])[0]:
            return f"mutation of {module.strip()}"
    return ""


def _clear(repo, work: Path) -> None:
    guard._git(["worktree", "remove", "--force", str(work / "tree")], repo)
    shutil.rmtree(work, ignore_errors=True)
    guard._git(["worktree", "prune"], repo)


def tested(repo, item: dict, run=None) -> str:
    """Run the suite on the item's tree in a fresh worktree whose commit has base and head as parents; '' when it passed."""
    work = root() / item["head"][:12]
    _clear(repo, work)
    commit = _out(repo, "-c", "user.name=merge-gate", "-c", "user.email=merge-gate@localhost", "commit-tree",
                  item["tree"], "-p", item["base"], "-p", item["head"], "-m", f"merge gate: {item['key']}")
    _out(repo, "worktree", "add", "-q", "--detach", str(work / "tree"), commit)
    try:
        return suite(work / "tree", item["base"], work / "home", run)
    finally:
        _clear(repo, work)


def _settle(repo, item: dict, gh, run) -> dict:
    where = f"{item['key']} on {item['base'][:12]}"
    if not item["tree"]:
        item["state"] = FAILURE
        post(item["head"], FAILURE, f"{where}: does not merge onto main", gh)
        return item
    post(item["head"], PENDING, f"{where}: running", gh)
    try:
        failed = tested(repo, item, run)
        item["state"], said = (FAILURE, f"{failed} failed") if failed else (SUCCESS, "passed")
    except (GateError, guard.GhError, OSError, subprocess.SubprocessError) as exc:
        item["state"], said = ERROR, f"not tested: {exc}"
    post(item["head"], item["state"], f"{where}: {said}", gh)
    return item


def run_pass(repo, only: int | None = None, again: bool = False, gh=None, run=None, say=print) -> list[dict]:
    """Test main's tip and each candidate pull request whose merged tree has no verdict, and post one; the rows it judged."""
    from harness import exclusive
    gh = gh or (lambda argv: guard._gh(argv, cwd=str(repo)))
    def due(pr):
        try:
            item = plan(repo, pr, gh)
        except (GateError, guard.GhError, ValueError, LookupError, TypeError) as exc:
            say(f"not planned, {'main' if pr is None else '#' + str(pr.get('number'))}: {exc}")
            return None
        return item if again or item["state"] not in FINAL else None
    fd = os.open(root() / "lock", os.O_RDWR | os.O_CREAT, 0o644)
    held = exclusive._take(fd)
    try:
        if not held:
            say("another merge gate pass is running")
            return []
        wanted = [pr for pr in candidates(gh) if only in (None, pr["number"])]
        if only is not None and not wanted:
            raise GateError(f"#{only} is not an open, non-draft pull request on main from this repository's own branch")
        todo = [i for i in map(due, ([None] if only is None else []) + wanted) if i]
        for i in todo:
            if i["tree"]:
                post(i["head"], PENDING, f"{i['key']} on {i['base'][:12]}: queued", gh)
        rows = []
        for i in todo:
            # main may have moved while the ones before this were tested
            now = due(i["pr"])
            if now:
                rows.append(_settle(repo, now, gh, run))
        return rows
    finally:
        if held:
            exclusive._release(fd)
        os.close(fd)


def _refs(src) -> str:
    return _out(src, "ls-remote", "origin", "refs/heads/main", "refs/pull/*/head")


def queue(src=None, conn=None, refs=None) -> dict | None:
    """On the scheduler, queue one pass as a cpu job when origin's main or a pull request head moved since the last one queued; else None."""
    from harness import deploy, resources
    from harness import workqueue as wq
    src = Path(src) if src is not None else paths.deploy_checkout()
    if src is None or not (src / ".git").exists() or paths.role() != paths.SCHEDULER:
        return None
    mark = hashlib.sha256((refs or _refs)(src).encode()).hexdigest()
    seen = root() / "seen"
    if seen.exists() and seen.read_text(encoding="utf-8").strip() == mark:
        return None
    with wq._store(conn) as c:
        if wq._select(c, "WHERE requested_by = ? AND state IN (?, ?)", (REQUESTER, wq.PENDING, wq.RUNNING)):
            return None
        job = wq.add([*deploy.SOH, "merge-gate", "--repo", str(src)], title="merge gate", cwd=str(src),
                     resource=resources.CPU, requested_by=REQUESTER, conn=c)
    seen.write_text(mark, encoding="utf-8")
    return job
