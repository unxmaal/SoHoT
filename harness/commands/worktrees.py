"""`soh worktrees`: every git worktree and whether its pull request merged; --prune removes the merged, clean ones (#2114)."""
from __future__ import annotations

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    p = sub.add_parser("worktrees", help="list every git worktree with what --prune would do to it and why")
    p.add_argument("--prune", action="store_true",
                   help="remove each worktree whose pull request merged and whose tracked files are unchanged: the "
                        "folder, its untracked scratch and the git entry; the branch stays")
    p.set_defaults(func=cmd_worktrees)


def cmd_worktrees(a) -> int:
    from harness import worktrees
    try:
        trees = worktrees.prune() if a.prune else worktrees.survey()
    except worktrees.StepError as exc:
        note(f"worktrees: {exc}")
        emit(ok=False, error=str(exc))
        return 1
    for line in worktrees.lines(trees, a.prune):
        note(line)
    emit(pruned=bool(a.prune), worktrees=[{"path": str(t.path), "branch": t.branch, "action": t.action, "why": t.why,
                                           "pr": t.pr, "scratch": t.scratch} for t in trees])
    return 0
