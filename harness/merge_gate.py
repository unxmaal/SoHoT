"""The local merge gate: test a pull request's head merged onto main in a clean worktree and post the verdict as a commit status (#2110)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from harness import deploy_guard as guard
from harness import paths

#: A `--pr` call waits this long for the lock another pass holds, polling at LOCK_POLL_S, then reports the verdict its tree has. #2206
LOCK_POLL_S = 5.0
WAIT_S = 14400.0
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
#: Passes that start a tree and die before its verdict, after which the poll stops queueing another for it. #2140
RETRY_MAX = 3
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


def _open_path() -> Path:
    return root() / "open.json"


def opened() -> dict:
    """{head: {"text", "tries"}} for each pending status this machine posted that no final verdict has replaced."""
    try:
        got = json.loads(_open_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {"": {"text": "the record of pending verdicts is unreadable", "tries": 0}}
    return got if isinstance(got, dict) else {"": {"text": "the record of pending verdicts is unreadable", "tries": 0}}


def _track(head: str, state: str, text: str, started: bool = False) -> None:
    from harness import atomic_file
    rows = opened()
    if state == PENDING:
        rows[head] = {"text": text, "tries": rows.get(head, {}).get("tries", 0) + (1 if started else 0)}
    else:
        rows.pop(head, None)
    tmp = _open_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, sort_keys=True), encoding="utf-8")
    atomic_file.replace(tmp, _open_path())


def _again_path() -> Path:
    return root() / "again"


def _holder() -> bool:
    from harness import exclusive
    return exclusive._taken(root() / "lock")


def stranded() -> dict:
    """The pending statuses no pass is working on: a pass that held the lock died, or one that found it held has nobody to run for it."""
    if _holder():
        return {}
    got = dict(opened())
    if _again_path().exists():
        got.setdefault("", {"text": "a pass found the lock held and the holder is gone", "tries": 0})
    return got


def post(head: str, state: str, text: str, gh, started: bool = False) -> None:
    gh(["api", "-X", "POST", f"repos/{{owner}}/{{repo}}/statuses/{head}", "-f", f"state={state}",
        "-f", f"context={CONTEXT}", "-f", f"description={text[:DESCRIPTION_MAX]}"])
    _track(head, state, text, started)


def plan(repo, pr: dict | None, gh) -> dict:
    """What testing `pr` (None: main's own tip) tests now: head, base, the merged tree, and whether that tree has its verdict."""
    _out(repo, "fetch", "-q", "--no-tags", "origin", "main")
    main = _out(repo, "rev-parse", "FETCH_HEAD^{commit}")
    if pr is None:
        tree = _out(repo, "rev-parse", f"{main}^{{tree}}")
        state = {guard.PASSED: SUCCESS, guard.FAILED: FAILURE}.get(guard.gated(main, gh, repo)[0], "")
        return {"pr": None, "head": main, "base": _out(repo, "rev-parse", f"{main}^"), "tree": tree,
                "key": guard.stamp(tree), "state": state, "since": 0}
    head = pr["headRefOid"]
    _out(repo, "fetch", "-q", "--no-tags", "origin", f"refs/pull/{pr['number']}/head")
    tree = merged(repo, main, head)
    key = guard.stamp(tree) if tree else f"conflict {main}"
    since = int(_out(repo, "log", "-1", "--format=%ct", head))
    return {"pr": pr, "head": head, "base": main, "tree": tree, "key": key, "state": verdict(head, key, gh), "since": since}


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
    post(item["head"], PENDING, f"{where}: running", gh, started=True)
    try:
        failed = tested(repo, item, run)
        item["state"], said = (FAILURE, f"{failed} failed") if failed else (SUCCESS, "passed")
    except (GateError, guard.GhError, OSError, subprocess.SubprocessError) as exc:
        item["state"], said = ERROR, f"not tested: {exc}"
    post(item["head"], item["state"], f"{where}: {said}", gh)
    return item


def run_pass(repo, only: int | None = None, again: bool = False, gh=None, run=None, say=print, wait: float = 0.0,
             sleep=time.sleep, clock=time.monotonic) -> list[dict]:
    """Test main's tip and each open pull request whose merged tree has no verdict, longest-waiting first, and post one; the rows it judged.

    A pass that finds the lock held leaves a mark, and the holder runs one more pass when it lets go. #2140
    With `only` and `wait`, the call waits that long for the holder, and a tree the holder judged comes back as a row with `cached` set. #2206
    """
    gh = gh or (lambda argv: guard._gh(argv, cwd=str(repo)))
    held, rows = _pass(repo, only, again, gh, run, say, wait, sleep, clock)
    while held:
        try:
            _again_path().unlink()
        except FileNotFoundError:
            break
        held, more = _pass(repo, None, False, gh, run, say, 0.0, sleep, clock)
        rows += more
    if only is not None and wait > 0 and not any((r["pr"] or {}).get("number") == only for r in rows):
        rows += _recorded(repo, only, gh, say)
    return rows


def _recorded(repo, number: int, gh, say) -> list[dict]:
    """The verdict an earlier pass left on pull request `number`'s current tree, as a row; [] when it has none."""
    try:
        pr = next((p for p in candidates(gh) if p["number"] == number), None)
        item = plan(repo, pr, gh) if pr else None
    except (GateError, guard.GhError, ValueError, LookupError, TypeError) as exc:
        say(f"not planned, #{number}: {exc}")
        return []
    return [{**item, "cached": True}] if item and item["state"] in FINAL else []


def _lock(fd: int, wait: float, say, sleep, clock) -> bool:
    """Take the lock, waiting up to `wait` seconds for its holder while leaving the mark that makes it run one more pass."""
    from harness import cuts, exclusive
    _again_path().touch()
    if exclusive._take(fd):
        _again_path().unlink(missing_ok=True)
        return True
    if wait <= 0:
        return False
    say(f"another merge gate pass is running: waiting up to {int(wait)} s for it")
    end = clock() + wait
    try:
        with cuts.timeout("merge_gate_wait", "a merge gate call waiting for the pass that holds the lock"):
            while True:
                if exclusive._take(fd):
                    _again_path().unlink(missing_ok=True)
                    return True
                if clock() >= end:
                    raise TimeoutError(f"the lock was held for {int(wait)} s")
                _again_path().touch()
                sleep(LOCK_POLL_S)
    except TimeoutError:
        return False


def _pass(repo, only, again, gh, run, say, wait=0.0, sleep=time.sleep, clock=time.monotonic) -> tuple[bool, list[dict]]:
    from harness import exclusive
    def due(pr):
        try:
            item = plan(repo, pr, gh)
        except (GateError, guard.GhError, ValueError, LookupError, TypeError) as exc:
            say(f"not planned, {'main' if pr is None else '#' + str(pr.get('number'))}: {exc}")
            return None
        return item if again or item["state"] not in FINAL else None
    fd = os.open(root() / "lock", os.O_RDWR | os.O_CREAT, 0o644)
    held = _lock(fd, wait, say, sleep, clock)
    try:
        if not held:
            say("another merge gate pass is running")
            return False, []
        rows, tried, queued, first = [], set(), set(), True
        # the open pull requests are listed again before each tree, so one that merged, closed or moved while another was tested is not
        while True:
            wanted = [pr for pr in candidates(gh) if only in (None, pr["number"])]
            if only is not None and not wanted:
                if first:
                    raise GateError(f"#{only} is not an open, non-draft pull request on main from this repository's own branch")
                break
            first = False
            todo = [i for i in map(due, ([None] if only is None else []) + wanted) if i and (i["head"], i["key"]) not in tried]
            if only is None:
                for head in set(opened()) - {pr["headRefOid"] for pr in wanted} - {i["head"] for i in todo}:
                    _track(head, FAILURE, "")
            for i in todo:
                if i["tree"] and (i["head"], i["key"]) not in queued:
                    queued.add((i["head"], i["key"]))
                    post(i["head"], PENDING, f"{i['key']} on {i['base'][:12]}: queued", gh)
            if not todo:
                break
            item = min(todo, key=lambda i: (i["pr"] is not None, i["since"], (i["pr"] or {}).get("number", 0)))
            tried.add((item["head"], item["key"]))
            rows.append(_settle(repo, item, gh, run))
        return True, rows
    finally:
        if held:
            exclusive._release(fd)
        os.close(fd)


def _refs(src) -> str:
    return _out(src, "ls-remote", "origin", "refs/heads/main", "refs/pull/*/head")


def queue(src=None, conn=None, refs=None) -> dict | None:
    """On the scheduler, queue one pass as a cpu job when origin's main or a pull request head moved since the last one queued, or a pass died with a pending status; else None."""
    src = Path(src) if src is not None else paths.deploy_checkout()
    if src is None or not (src / ".git").exists() or paths.role() != paths.SCHEDULER:
        return None
    mark = hashlib.sha256((refs or _refs)(src).encode()).hexdigest()
    seen = root() / "seen"
    moved = not (seen.exists() and seen.read_text(encoding="utf-8").strip() == mark)
    if not moved and not retestable():
        return None
    job = enqueue(src, conn)
    if job and moved:
        seen.write_text(mark, encoding="utf-8")
    return job


def retestable() -> dict:
    """What `stranded` finds that the poll may still queue a pass for: a tree whose passes have died RETRY_MAX times waits for the owner."""
    from harness import cuts
    rows = stranded()
    kept = {h: v for h, v in rows.items() if not h or v.get("tries", 0) < RETRY_MAX}
    if len(kept) < len(rows):
        cuts.cut("merge_gate_retries", "stranded merge gate verdicts", kept=len(kept), dropped=len(rows) - len(kept))
    return kept


def enqueue(src, conn=None) -> dict | None:
    """One cpu pass for `src` unless one waits or runs already."""
    from harness import deploy, resources
    from harness import workqueue as wq
    with wq._store(conn) as c:
        if wq._select(c, "WHERE requested_by = ? AND state IN (?, ?)", (REQUESTER, wq.PENDING, wq.RUNNING)):
            return None
        return wq.add([*deploy.SOH, "merge-gate", "--repo", str(src)], title="merge gate", cwd=str(src),
                      resource=resources.CPU, requested_by=REQUESTER, conn=c)
