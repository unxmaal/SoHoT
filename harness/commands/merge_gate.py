"""`soh merge-gate`: The local merge gate: test a pull request's head merged onto main in a clean worktree and post the verdict as a commit status (#2110)."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("merge-gate", help="The local merge gate: test a pull request's head merged onto main in a clean worktree and post the verdict as a commit status")
    p.add_argument("--pr", type=int, default=None, help="only this pull request (default: main's tip and every open one)")
    p.add_argument("--repo", default="", help="the checkout whose origin is tested (default: the deploy checkout, else this one)")
    p.add_argument("--again", action="store_true", help="test a tree again though it has its verdict")
    p.add_argument("--queue", action="store_true", help="queue one pass as a cpu job and return, for a button that cannot wait out a suite")
    p.set_defaults(func=cmd_merge_gate)


def cmd_merge_gate(a) -> int:
    from harness import deploy_guard, merge_gate, paths
    repo = Path(a.repo) if a.repo else (paths.deploy_checkout() or paths.REPO)
    if a.queue:
        job = merge_gate.enqueue(repo)
        note(f"queued {job['id']}: {job['title']}" if job else "a merge gate pass already waits or runs")
        emit(job=job)
        return 0
    try:
        rows = merge_gate.run_pass(repo, only=a.pr, again=a.again, say=note)
    except (merge_gate.GateError, deploy_guard.GhError) as exc:
        return err(f"merge gate: {exc}")
    for r in rows:
        who = f"#{r['pr']['number']}" if r["pr"] else "main"
        note(f"{who} {r['head'][:12]} on {r['base'][:12]}: {r['state']} ({r['key'][:17]})")
    if not rows:
        note("nothing to test: every tree has its verdict")
    emit(rows=rows)
    return 1 if any(r["state"] == merge_gate.ERROR for r in rows) else 0
