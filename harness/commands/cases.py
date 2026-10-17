"""`soh cases import|control|regrade|labels <source>`: an importer, its control, a repo run regraded, fairness labels. #603, #887, #940, #920."""
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
    if a.action == "labels":
        if a.source != "repo":
            return err("only the repo lane has fairness labels")
        return _repo_labels(Path(a.out) if a.out else importers.CASES, a.packets)
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
    """Validate every repo case test by test and keep each verdict for evals.run to read. #920."""
    import time
    from evals import environment, repo
    from evals.core import load_cases
    from harness import memory_store as ms
    from harness import paths
    machine = ms.this_machine()["fingerprint"]
    commit = environment._sh("git", "-C", str(paths.REPO), "rev-parse", "--short=12", "HEAD")
    got, counts, memo = {}, {}, {}
    for case in load_cases(root / "repo"):
        rec = repo.save_validation(case, repo.controls(case, memo=memo), machine, commit, time.time())
        got[case.id] = rec["verdict"]
        kind = rec["verdict"].split(":", 1)[0]
        counts[kind] = counts.get(kind, 0) + 1
        note(f"  {case.id}: {rec['verdict']}")
    note("  " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())))
    sound = bool(got) and set(counts) == {"valid"}
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
        rows.append({"file": path.name, "case": cid, "was_resolved": bool(was.get("resolved")),
                     "was_applied": bool(was.get("patch_applied")), "resolved": g.resolved,
                     "patch_applied": g.patch_applied, "detail": g.detail})
        note(f"  {path.name}: {'resolved' if g.resolved else 'applied, unresolved' if g.patch_applied else 'invalid_patch'}"
             f" (was {'resolved' if was.get('resolved') else 'applied' if was.get('patch_applied') else 'invalid_patch'})"
             f"{'' if g.resolved else ': ' + g.detail[:200]}")
    if only and not {r["case"] for r in rows} >= set(only):
        return err(f"no stored diff in {run} for {', '.join(sorted(set(only) - {r['case'] for r in rows}))}")
    emit(bool(rows), regraded=rows)
    return 0 if rows else 1


def _repo_labels(root: Path, packets: str) -> int:
    """Kappa per axis, the cases both labellers flag and those they dispute; or write labeller packets. #920."""
    from evals import fairness
    from evals.core import load_cases
    cases = load_cases(root / "repo")
    if packets:
        out = Path(packets)
        out.mkdir(parents=True, exist_ok=True)
        for case in cases:
            (out / f"{case.id}.md").write_text(fairness.packet(case), encoding="utf-8")
        note(f"{len(cases)} packets under {out}")
        return 0
    labels = fairness.load(root / "repo" / fairness.LABELS.name)
    wrong = fairness.check(labels, [c.id for c in cases])
    if wrong:
        for line in wrong:
            note(f"  {line}")
        return err(f"{len(wrong)} problem(s) in the labels")
    got = fairness.summary(labels, [c.id for c in cases])
    for axis, k in got["kappa"].items():
        note(f"  kappa {axis}: {'undefined' if k is None else f'{k:.2f}'}")
    for kind in ("flagged", "disputed"):
        for cid, axes in sorted(got[kind].items()):
            note(f"  {kind} {cid}: {', '.join(axes)}")
    emit(True, **got)
    return 0
