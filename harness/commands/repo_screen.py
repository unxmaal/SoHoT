"""`soh repo-screen`: the repo exam's screening subset, its anchors, and the verdict over screen runs (#1176)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from harness.commands.common import emit, err, note


def _cases(a):
    from evals.core import load_cases
    from evals.importers import CASES
    return load_cases(Path(a.cases) if getattr(a, "cases", "") else CASES / "repo")


def _anchors(a) -> dict:
    from evals import repo_screen
    return repo_screen.load_anchors(Path(a.anchors) if getattr(a, "anchors", "") else None)


def pick_text(got: dict) -> str:
    lines = [f"screen subset: {got['n']} of {got['of']} repo cases, {got['tasks']} tasks, digest {got['digest']}"]
    for key, s in sorted(got["strata"].items()):
        lines.append(f"  {key:30} {len(s['picked']):>2}/{s['cases']:<3} {' '.join(s['picked'])}")
    lines.append("  anchor classes: " + ", ".join(f"{k} {v}" for k, v in sorted(got["classes"].items())))
    for side in ("base", "reference"):
        lines.append(f"  {side} run {got[side]['run']}: {got[side]['passed']}/{got['n']} passed on the subset")
    lines.append("run it: uv run python -m evals.run --modality repo --repo-screen --candidates <spec> --out <dir>")
    return "\n".join(lines)


def verdict_text(v: dict) -> str:
    s, b = v["speed"], v["base_speed"]
    return "\n".join([
        f"{v['candidate']}: {v['passed']}/{v['rows']} rows passed over {v['draws']} draw(s) of {v['cases']} cases "
        f"({v['tasks']} tasks); base {v['base_passed']}/{v['base_rows']}",
        f"  tasks: wins {v['task_wins']}, losses {v['task_losses']}, sign p {v['sign_p']}",
        f"  speed: median {s['median_s']} s/case, {s['tokens_per_s']} tok/s; base {b['median_s']} s/case, "
        f"{b['tokens_per_s']} tok/s",
        f"  {v['verdict'].upper()}: {v['why']}"])


def cmd_repo_screen(a) -> int:
    """Print the screening subset, write its anchors from two stored runs, or judge screen runs against the base."""
    from evals import repo_report, repo_screen
    try:
        cases, anchors = _cases(a), _anchors(a)
        if a.action == "pick":
            chosen = repo_screen.pick(cases, a.n or None, anchors)
            got = repo_screen.describe(cases, chosen, anchors)
            note(pick_text(got))
            emit(True, **got)
            return 0
        if a.action == "anchors":
            if len(a.runs) != 2:
                return err("repo-screen anchors takes two runs: the base, then the reference")
            runs, rows, _, _ = repo_report.stored(a.runs, store=a.store or None, match=False)
            got = repo_screen.anchors_from(runs, rows)
            out = Path(a.anchors) if a.anchors else repo_screen.ANCHORS
            if a.write:
                out.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
                note(f"wrote {out}")
            else:
                note(json.dumps(got, indent=1))
            emit(True, path=str(out), written=bool(a.write), **got)
            return 0
        if not a.runs:
            return err("repo-screen verdict needs the screen runs")
        base = a.base or (anchors.get("base") or {}).get("run")
        if not base:
            return err("no base run: pass --base or commit the anchors")
        runs, rows, _, _ = repo_report.stored([base, *a.runs], store=a.store or None, match=False)
        want = repo_screen.describe(cases, repo_screen.pick(cases, None, anchors), anchors)
        for r in runs[1:]:
            ids = sorted(r["receipt"].get("case_ids") or [])
            if ids != want["case_ids"]:
                return err(f"run {r['id']} did not run the current screen subset ({len(ids)} cases, "
                           f"want {want['n']}, digest {want['digest']}); screens are compared on one subset")
        got = repo_screen.verdict([x for x in rows if x["run_id"] == int(base)],
                                  [x for x in rows if x["run_id"] != int(base)], cases,
                                  outside_votes=a.outside_votes)
    except (repo_screen.Refused, repo_report.Refused, OSError, sqlite3.Error) as exc:
        return err(f"repo screen refused: {exc}")
    note(verdict_text(got))
    emit(True, base=int(base), runs=list(a.runs), **got)
    return 0
