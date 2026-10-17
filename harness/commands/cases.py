"""`soh cases import|control|regrade <source>`: an importer, its negative control, or a repo run's stored diffs regraded. #603, #887, #940."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, err, note


def cmd_cases(a) -> int:
    from evals import importers
    from evals.core import load_cases
    if a.source == "repo" and a.action == "control":
        return _repo_controls(Path(a.out) if a.out else importers.CASES)
    if a.action == "regrade":
        if a.source != "repo" or not a.run:
            return err("regrade takes `repo --run <run dir>`")
        return _repo_regrade(Path(a.out) if a.out else importers.CASES, Path(a.run), a.case or [])
    try:
        mod = importers.module(a.source)
    except ValueError as exc:
        return err(str(exc))
    root = Path(a.out) if a.out else importers.CASES
    if a.action == "import":
        written = importers.run(a.source, root=root)
        note(f"{len(written)} cases from {mod.SOURCE}@{mod.REVISION[:12]} under "
             f"{root / mod.LANE / a.source}")
        emit(bool(written), cases=len(written))
        return 0 if written else 1
    cases = load_cases(root / mod.LANE / a.source)
    got = importers.negative_control(cases, mod.RESPONDERS, mod.passes)
    for name, (passed, total) in got.items():
        note(f"  {name} {passed}/{total}")
    emit(True, control={k: list(v) for k, v in got.items()})
    return 0


def _repo_controls(root: Path) -> int:
    from evals import repo
    from evals.core import load_cases
    sound, got = True, {}
    for case in load_cases(root / "repo"):
        try:
            c = repo.controls(case.params)
        except repo.RepoEnvError as exc:
            return err(f"{case.id}: environment: {exc}")
        ok = c["reference"]["resolved"] and not c["empty"]["resolved"]
        sound &= ok
        got[case.id] = c
        note(f"  {case.id}: empty {'resolves' if c['empty']['resolved'] else 'fails'}, reference "
             f"{'resolves' if c['reference']['resolved'] else 'fails: ' + c['reference']['detail']}"
             f"{'' if ok else '  UNSOUND'}")
    emit(sound, control=got)
    return 0 if sound else 1


def _repo_regrade(root: Path, run: Path, only: list[str]) -> int:
    """Each stored diff of a repo run through today's apply and grader; the run and the store are not touched."""
    import json
    from evals import repo
    from evals.core import load_cases
    cases = {c.id: c for c in load_cases(root / "repo")}
    rows = []
    for path in sorted(run.glob("*--*.json")):
        stored = json.loads(path.read_text(encoding="utf-8"))
        cid = stored.get("case") if isinstance(stored, dict) else None
        if cid not in cases or (only and cid not in only) or "diff" not in stored:
            continue
        try:
            a = repo.Attempt.open(cases[cid].params)
        except repo.RepoEnvError as exc:
            return err(f"{cid}: environment: {exc}")
        try:
            g = a.submit(stored["diff"])
        finally:
            a.close()
        was = stored.get("grade") or {}
        rows.append({"run": run.name, "file": path.name, "case": cid,
                     "was_resolved": bool(was.get("resolved")), "was_applied": bool(was.get("patch_applied")),
                     "resolved": g.resolved,
                     "patch_applied": g.patch_applied, "detail": g.detail})
        note(f"  {path.name}: {'resolved' if g.resolved else 'applied, unresolved' if g.patch_applied else 'invalid_patch'}"
             f" (was {'resolved' if was.get('resolved') else 'applied' if was.get('patch_applied') else 'invalid_patch'})"
             f"{'' if g.resolved else ': ' + g.detail[:200]}")
    if only and not {r["case"] for r in rows} >= set(only):
        return err(f"no stored diff in {run} for {', '.join(sorted(set(only) - {r['case'] for r in rows}))}")
    emit(bool(rows), regraded=rows)
    return 0 if rows else 1
