"""Agent worktrees whose branch's pull request merged, with no change to tracked files, removed (#2114)."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

STEP_TIMEOUT_S = 60.0
REMOVE, KEEP = "remove", "keep"
GH = "gh"
#: Read without taking the index lock an agent at work in that worktree may want.
STATUS = ("git", "--no-optional-locks", "status", "--porcelain")
#: The pull requests read for one branch name, newest first: a name used again shows its open one beside the merged.
PRS_READ = 20


class StepError(RuntimeError):
    pass


@dataclass
class Tree:
    path: Path
    branch: str = ""
    head: str = ""
    main: bool = False
    locked: bool = False
    action: str = KEEP
    why: str = ""
    pr: int | None = None
    scratch: int = 0


def checkout() -> Path:
    """The checkout whose repository's worktrees are read; tests point this at a scratch repository."""
    from harness import paths
    return paths.REPO


def protected() -> list[Path]:
    """Folders never removed whatever their branch says: the releases, the deploy checkout, the checkout running this."""
    from harness import deploy, paths
    live = paths.DEFAULT_HOME / deploy.releases_dir().name
    return [p for p in (deploy.releases_dir(), live, paths.deploy_checkout(), checkout()) if p is not None]


def _ask(argv: list[str], cwd: Path) -> str:
    what = " ".join(argv[:3])
    try:
        got = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=STEP_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise StepError(f"{what} did not run: {exc}") from exc
    if got.returncode != 0:
        raise StepError(f"{what} failed (rc {got.returncode}): {(got.stderr or got.stdout).strip()[:200]}")
    return got.stdout


def listed(repo: Path) -> list[Tree]:
    """Every worktree of repo's repository as git lists them: the main checkout first, and marked."""
    out: list[Tree] = []
    for block in _ask(["git", "worktree", "list", "--porcelain"], repo).split("\n\n"):
        got = {k: v for k, _, v in (line.partition(" ") for line in block.splitlines())}
        if "worktree" in got:
            out.append(Tree(Path(got["worktree"]), got.get("branch", "").removeprefix("refs/heads/"),
                            got.get("HEAD", ""), main=not out, locked="locked" in got))
    return out


def _inside(path: Path, root: Path) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(root))


def _tracked(path: Path) -> int:
    return len(_ask([*STATUS, "--untracked-files=no"], path).splitlines())


def _local(t: Tree, roots: list[Path]) -> str:
    """Why t stays before any pull request is read, or ''."""
    if t.main:
        return "the main checkout"
    if any(_inside(t.path, r) for r in roots):
        return "a release or the checkout this runs from"
    if not t.branch:
        return "no branch, so no pull request"
    if t.locked:
        return "locked"
    if not t.path.is_dir():
        return "its folder is gone; `git worktree prune` clears the entry"
    changed = _tracked(t.path)
    return f"{changed} uncommitted change(s) to tracked files" if changed else ""


def _pull(t: Tree, repo: Path) -> str:
    """Why t's pull requests keep it, or '' with t.pr the merged one its HEAD is a commit of or was committed before."""
    prs = json.loads(_ask([GH, "pr", "list", "--head", t.branch, "--state", "all", "-L", str(PRS_READ), "--json",
                           "number,state,headRefOid,mergedAt,commits"], repo))
    if not prs:
        return "no pull request"
    for p in prs:
        if p["state"] == "OPEN":
            return f"PR #{p['number']} is open"
    merged = [p for p in prs if p["state"] == "MERGED"]
    if not merged:
        return f"PR #{prs[0]['number']} closed without merging"
    for p in merged:
        if t.head in {p.get("headRefOid"), *(c.get("oid") for c in p.get("commits") or [])} or _before(t, p):
            t.pr = p["number"]
            return ""
    return f"HEAD {t.head[:12]} was committed after PR #{merged[0]['number']} merged and is not one of its commits"


def _before(t: Tree, pr: dict) -> bool:
    """Was t's HEAD committed by the time pr merged: a rebase pushed from elsewhere leaves such a HEAD behind."""
    at = _ask(["git", "log", "-1", "--format=%cI", "HEAD"], t.path).strip()
    return datetime.fromisoformat(at) <= datetime.fromisoformat(pr["mergedAt"])


def _deepest(trees: list[Tree]) -> list[Tree]:
    return sorted(trees, key=lambda t: -len(t.path.parts))


def survey(repo: Path | None = None, roots: list[Path] | None = None, holding=None) -> list[Tree]:
    """Every worktree with what prune() would do to it and why. Removes nothing."""
    from harness import holders
    trees = listed(Path(repo or checkout()))
    roots = protected() if roots is None else roots
    for t in trees:
        try:
            t.why = _local(t, roots) or _pull(t, trees[0].path)
        except (StepError, ValueError, KeyError, TypeError) as exc:
            t.why = f"not read: {exc}"
    free = [t for t in trees if not t.why]
    held = (holding or holders.holding)([t.path for t in free]) if free else {}
    for t in _deepest(free):
        inner = [o for o in trees if o is not t and o.action == KEEP and _inside(o.path, t.path)]
        if held is None:
            t.why = "no way to tell on this platform which live processes run from it"
        elif held.get(t.path):
            t.why = f"{len(held[t.path])} live process(es) run from it: {'; '.join(held[t.path][:3])}"
        elif inner:
            t.why = f"holds the worktree {inner[0].path.name}"
        else:
            try:
                t.scratch = len(_ask([*STATUS, "--ignored"], t.path).splitlines())
            except StepError as exc:
                t.why = f"not read: {exc}"
                continue
            t.action, t.why = REMOVE, f"PR #{t.pr} merged"
    return trees


def prune(repo: Path | None = None, roots: list[Path] | None = None, holding=None) -> list[Tree]:
    """survey(), then each worktree it marks goes: the folder, its untracked scratch and the git entry. The branch stays."""
    trees = survey(repo, roots, holding)
    for t in _deepest([t for t in trees if t.action == REMOVE]):
        try:
            changed = _tracked(t.path)
            if changed:
                raise StepError(f"{changed} uncommitted change(s) to tracked files since it was read")
            _ask(["git", "worktree", "remove", "--force", str(t.path)], trees[0].path)
        except StepError as exc:
            t.action, t.why = KEEP, f"not removed: {exc}"
    return trees


def lines(trees: list[Tree], pruned: bool) -> list[str]:
    """The count, then one line a worktree: what became of it and why; untracked scratch that went with it is named."""
    gone, kept = ("removed", "kept") if pruned else ("would remove", "keep")
    n = sum(t.action == REMOVE for t in trees)
    out = [f"  agent worktrees: {gone} {n}, {kept} {len(trees) - n}"]
    for t in trees:
        verb = gone if t.action == REMOVE else "kept"
        scratch = f"; {t.scratch} untracked path(s) {'went' if pruned else 'go'} with it" if t.scratch else ""
        out.append(f"    {verb} {t.path} [{t.branch or 'detached'}]: {t.why}{scratch if t.action == REMOVE else ''}")
    return out


def sweep(say=print) -> dict:
    """The loop's disk step: prune() from the live home only, every worktree reported. Never raises."""
    from harness import monitor
    if not monitor.live_home():
        got = {"skipped": "this is not the live home"}
    else:
        try:
            trees = prune()
            got = {"removed": [str(t.path) for t in trees if t.action == REMOVE],
                   "kept": [str(t.path) for t in trees if t.action == KEEP]}
        except (StepError, OSError) as exc:
            got = {"skipped": str(exc)}
    for line in [f"  agent worktrees not pruned: {got['skipped']}"] if "skipped" in got else lines(trees, True):
        say(line)
    return got
