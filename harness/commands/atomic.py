"""`soh atomic`: #891's repo cases rerun decomposed: Claude plans subtasks and a hidden check, the local model writes them, three arms scored. #1690."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    p = sub.add_parser("atomic", help="rerun the repo-lane cases decomposed: Claude (claude -p) writes subtask specs "
                       "and a hidden check, the local model writes each function or file in up to 3 fresh attempts, "
                       "a failed case goes to the recorded cloud answer; prints cloud-only, routed and atomic")
    p.add_argument("--out", required=True, help="the run directory: plans, case records, report, scratch home")
    p.add_argument("--case", action="append", default=[], help="a case id (repeatable; default every case both "
                   "stored runs hold)")
    p.add_argument("--stride", type=int, default=1, help="every Nth case in id order, a subset that spans the repos")
    p.add_argument("--first", type=int, default=0, help="only the first N cases (after --stride) in id order")
    p.add_argument("--model", default="", help="the planning model for claude -p (default claude-opus-5-5)")
    p.add_argument("--local-model", default="", help="the local model spec (default the code lane's adopted one)")
    p.add_argument("--attempts", type=int, default=0, help="fresh local attempts per case (default 3)")
    p.add_argument("--local-run", type=int, default=0, help="the stored local run of the routed arm (default 571)")
    p.add_argument("--cloud-run", type=int, default=0, help="the stored cloud run (default 572)")
    p.add_argument("--store", default="", help="the store the runs are read from, read-only (default the live one)")
    p.add_argument("--cases", default="", help="the repo cases directory (default evals/cases/repo)")
    p.add_argument("--report-only", action="store_true", help="score the records already under --out; plan and "
                   "run nothing")
    p.set_defaults(func=cmd_atomic)


def _rows(a) -> tuple[dict, dict]:
    from evals import atomic
    from harness import live_audit
    from harness import memory_store as ms
    conn = live_audit.open_readonly(Path(a.store) if a.store else ms.db_path())
    try:
        return (atomic.stored(conn, a.local_run or atomic.LOCAL_RUN),
                atomic.stored(conn, a.cloud_run or atomic.CLOUD_RUN))
    finally:
        conn.close()


def cmd_atomic(a) -> int:
    import json

    from evals import atomic, repo_routing
    from evals.core import load_cases
    from evals.importers import CASES
    from harness import delegate, exclusive, paths
    out = Path(a.out).expanduser().resolve()
    live_lock = exclusive.lock_path()
    if not a.report_only:
        held = delegate.busy() or atomic.lock_holders(live_lock)
        if held:
            note(f"atomic refused: the machine is held by {held}; rerun when it is free")
            emit(False, error=f"held by {held}")
            return 2
    try:
        local, cloud = _rows(a)
    except (repo_routing.Refused, OSError) as exc:
        note(f"atomic refused: {exc}")
        emit(False, error=str(exc))
        return 2
    if a.report_only:
        recs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "cases").glob("*.json"))}
        rep = atomic.report(recs, local, cloud)
    else:
        live = paths.home()
        atomic.seed_home(live, paths.eval_home(out / "home"))
        want = set(a.case)
        cases = sorted((c for c in load_cases(Path(a.cases) if a.cases else CASES / "repo")
                        if c.id in local and c.id in cloud and (not want or c.id in want)), key=lambda c: c.id)
        cases = cases[::a.stride] if a.stride > 1 else cases
        cases = cases[:a.first] if a.first else cases

        def progress(r) -> None:
            note(f"{r['case']:<36} {r.get('final', 'error'):5s} solved {int(bool(r.get('solved')))} "
                 f"attempts {len(r.get('attempts') or [])} "
                 + (f"escalate: {r['escalate'][:60]}" if r.get("escalate") else "")
                 + ("vacuous check" if r.get("vacuous") else "") + (f"error: {r['error'][:80]}" if r.get("error") else ""),
                 flush=True)
        rep = atomic.run(out, cases, local=local, cloud=cloud, model=a.model or atomic.CLOUD_MODEL,
                         attempts=a.attempts or atomic.ATTEMPTS, busy=lambda: atomic.lock_holders(live_lock),
                         progress=progress, local_model=a.local_model or None)
        if rep.get("stopped"):
            note(f"stopped before the next case: the machine is held by {rep['stopped']}; rerun to resume")
    for line in rep["lines"]:
        note(line)
    emit(**rep)
    return 0
