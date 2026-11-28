"""`soh merge-gate`: The local merge gate: test a pull request's head merged onto main in a clean worktree and post the verdict as a commit status (#2110)."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("merge-gate", help="The local merge gate: test a pull request's head merged onto main in a clean worktree and post the verdict as a commit status")
    p.add_argument("--pr", type=int, default=None, help="only this pull request (default: main's tip and every open one)")
    p.add_argument("--repo", default="", help="the checkout whose origin is tested (default: the deploy checkout, else this one)")
    p.add_argument("--wait", type=float, default=None, help="seconds to wait for a pass that holds the lock before giving up (default: the merge_gate_wait knob with --pr, none without)")
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
        wait = a.wait if a.wait is not None else (merge_gate.WAIT_S if a.pr is not None else 0.0)
        rows = merge_gate.run_pass(repo, only=a.pr, again=a.again, say=note, wait=wait)
    except (merge_gate.GateError, deploy_guard.GhError) as exc:
        return err(f"merge gate: {exc}")
    for r in rows:
        who = f"#{r['pr']['number']}" if r["pr"] else "main"
        note(f"{who} {r['head'][:12]} on {r['base'][:12]}: {r['state']} ({r['key'][:17]})"
             + (" (judged by an earlier pass)" if r.get("cached") else f", log {merge_gate.log_path(r['head'])}"))
    if not rows:
        note(f"no verdict for #{a.pr} yet" if a.pr is not None else "nothing to test: every tree has its verdict")
    emit(rows=rows)
    if a.pr is not None and not rows:
        return 1
    return 1 if any(r["state"] == merge_gate.ERROR for r in rows) else 0
