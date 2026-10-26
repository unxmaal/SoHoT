"""Offline routing over stored repo-lane runs: which executor a task goes to, scored on rows already graded. #891.

    soh repo-route --local RUN --cloud RUN [--agentic RUN] [--store PATH]

Reads the store read-only and writes nothing; router results stay apart from executor results.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from evals.importers.history import VARIANTS
from harness import intervals, reasons

#: Routes in cost order: a policy that can resolve a case on a cheaper route should.
ROUTES = ("local", "agentic", "cloud")
GATES = ("applies", "visible")
#: Deterministic labels from the prompt alone, first match wins; anything else is "none".
LABELS = (
    ("dependency_bump", re.compile(r"\b(bump|upgrade|pin)\b[^\n]{0,60}\b(to|from)\s+v?\d+\.\d+|\bdependabot\b", re.I)),
    ("formatter", re.compile(r"\b(ruff format|run black|black formatter|isort|reformat(ting)? the (code|file))\b", re.I)),
    ("linter_autofix", re.compile(r"\b(ruff check --fix|ruff --fix|autofix|lint(er)? (errors?|warnings?))\b", re.I)),
    ("codemod", re.compile(r"\bcodemod\b|\brename\b[^\n]{0,80}\b(across the (repo|codebase)|everywhere|"
                           r"every (call ?site|caller))\b", re.I)),
    ("scripted_edit", re.compile(r"\b(sed -i|find-and-replace|search and replace)\b", re.I)),
)


class Refused(Exception):
    """The runs cannot be routed over together; the message says why."""


def label(prompt: str) -> str:
    """The deterministic tool a task's prompt asks for, or none."""
    for name, pat in LABELS:
        if pat.search(prompt or ""):
            return name
    return "none"


def load(conn, run_id: int) -> dict:
    """case id -> {passed, applied, p2p_broken, seconds} for one run's first repeat."""
    if conn.execute("SELECT 1 FROM runs WHERE id = ?", (int(run_id),)).fetchone() is None:
        raise Refused(f"no run {run_id} in the store")
    out = {}
    for case, rep, passed, fc, sec, metrics, detail in conn.execute(
            "SELECT case_id, repeat_index, passed, failure_class, seconds, metrics, detail FROM results "
            "WHERE run_id = ? ORDER BY seq", (int(run_id),)):
        if (rep or 1) != 1 or "#" in case:
            continue
        m = json.loads(metrics or "{}")
        out[case] = {"passed": bool(passed), "applied": bool(m.get("patch_applied")), "failure_class": fc or "",
                     "p2p_broken": "pass_to_pass broken" in (detail or ""), "seconds": float(sec or 0.0)}
    return out


def gate(row: dict, kind: str) -> bool:
    """applies: the patch applied; visible: it applied and the tests that passed before still pass."""
    return row["applied"] and (kind == "applies" or not row["p2p_broken"])


def gate_table(rows: dict, kind: str) -> dict:
    """How far the gate predicts resolution: passes, resolved among them (precision), resolved it rejected."""
    on = [r for r in rows.values() if gate(r, kind)]
    off = [r for r in rows.values() if not gate(r, kind)]
    k = sum(r["passed"] for r in on)
    return {"rows": len(rows), "pass": len(on), "resolved_pass": k, "precision": round(k / len(on), 4) if on else 0.0,
            "ci95": list(intervals.wilson(k, len(on))), "fail": len(off),
            "resolved_fail": sum(r["passed"] for r in off),
            "base_rate": round(sum(r["passed"] for r in rows.values()) / len(rows), 4) if rows else 0.0}


def _cost(route: str, row: dict, acc: dict) -> None:
    if route == "cloud":
        acc["cloud_calls"] += 1
    else:
        acc["local_s"] += row["seconds"]


def policies(have: list[str]) -> dict:
    """name -> how it routes: ("fixed", route), ("cascade", [routes], gate), ("variant", {variant: route}), oracle."""
    local = [r for r in ("local", "agentic") if r in have]
    out = {"never-route": ("fixed", local[0]), "always-route": ("fixed", "cloud"), "oracle": ("oracle",)}
    for g in GATES:
        out[f"gate-{g}"] = ("cascade", ["local", "cloud"], g)
    if "agentic" in have:
        out["agentic-only"] = ("fixed", "agentic")
        out["gate-visible-agentic"] = ("cascade", ["local", "agentic", "cloud"], "visible")
    out["spec-local"] = ("variant", {"spec": "local", "symptom": "cloud"})
    return out


def score(by: dict, cases: list[str], variant: dict, how: tuple) -> dict:
    """One policy over the cases every route ran: resolved, cost and its wrong routes."""
    acc = {"resolved": 0, "cloud_calls": 0, "local_s": 0.0, "over_route": 0, "under_route": 0, "accepted_wrong": 0}
    local_routes = [r for r in ("local", "agentic") if r in by]
    for k in cases:
        if how[0] == "fixed":
            tried, final = [how[1]], how[1]
        elif how[0] == "variant":
            final = how[1].get(variant.get(k, ""), "cloud")
            tried = [final]
        elif how[0] == "oracle":
            final = next((r for r in ROUTES if r in by and by[r][k]["passed"]), local_routes[0])
            tried = [final]
        else:
            steps = [r for r in how[1] if r in by]
            tried = []
            for r in steps:
                tried.append(r)
                if r == steps[-1] or gate(by[r][k], how[2]):
                    break
            final = tried[-1]
            if final != "cloud" and not by[final][k]["passed"]:
                acc["accepted_wrong"] += 1
        for r in tried:
            _cost(r, by[r][k], acc)
        ok = by[final][k]["passed"]
        acc["resolved"] += ok
        if final == "cloud" and any(by[r][k]["passed"] for r in local_routes):
            acc["over_route"] += 1
        if not ok and any(by[r][k]["passed"] for r in by if r != final):
            acc["under_route"] += 1
    n = len(cases)
    return {**acc, "n": n, "rate": round(acc["resolved"] / n, 4) if n else 0.0,
            "ci95": list(intervals.wilson(acc["resolved"], n)), "local_s": round(acc["local_s"], 1),
            "cloud_share": round(acc["cloud_calls"] / n, 4) if n else 0.0}


def report(by: dict, meta: dict | None = None, runs: dict | None = None) -> dict:
    """Routes -> rows in, everything the text prints out. by: {route: {case: row}}; meta: {case: (prompt, variant)}."""
    if "local" not in by or "cloud" not in by:
        raise Refused("routing needs a local and a cloud run")
    meta = meta or {}
    shared = sorted(set.intersection(*(set(rows) for rows in by.values())))
    never = [k for k in shared if any(by[r][k]["failure_class"] in reasons.NEVER_RAN for r in by)]
    cases = [k for k in shared if k not in never]
    if not cases:
        raise Refused("the runs share no case the harness ran on every route")
    variant = {k: (meta[k][1] if k in meta else "") or next((v for v in VARIANTS if k.endswith(f"-{v}")), "")
               for k in cases}
    labels: dict = {}
    for k in cases:
        labels.setdefault(label(meta[k][0] if k in meta else ""), []).append(k)
    return {"runs": runs or {}, "cases": len(cases), "never_ran": never,
            "only": {r: len(set(rows) - set(shared)) for r, rows in by.items()},
            "executors": {r: {"resolved": sum(by[r][k]["passed"] for k in cases), "n": len(cases)} for r in by},
            "gates": {r: {g: gate_table({k: by[r][k] for k in cases}, g) for g in GATES} for r in by},
            "policies": {name: score(by, cases, variant, how) for name, how in policies(list(by)).items()},
            "labels": {lab: sorted(ks) for lab, ks in sorted(labels.items())}}


def _ci(k, n, ci) -> str:
    return f"{k}/{n} [{ci[0]:.2f}, {ci[1]:.2f}]"


def text(rep: dict) -> str:
    out = ["routes: " + ", ".join(f"{r} run {i}" for r, i in rep["runs"].items()),
           f"{rep['cases']} cases every route ran; left out, not run by every route: "
           + ", ".join(f"{r} {n}" for r, n in rep["only"].items())
           + f"; harness never ran on a route: {', '.join(rep['never_ran']) or 'none'}"]
    out.append("\napplicability gate per executor: applies = patch applied; visible = applied and pass_to_pass holds")
    for r, gs in rep["gates"].items():
        for g, t in gs.items():
            out.append(f"  {r:8s} {g:8s} pass {t['pass']:>4d}, resolved among them "
                       f"{_ci(t['resolved_pass'], t['pass'], t['ci95'])}; fail {t['fail']:>4d}, resolved among them "
                       f"{t['resolved_fail']}; base rate {t['base_rate']:.2f}")
    out.append("\npolicies (oracle is the ceiling; never-route and always-route are the executors' own rates)")
    out.append(f"  {'policy':22s} {'resolved':>20s} {'cloud':>6s} {'local s':>9s} {'over':>5s} {'under':>6s} "
               f"{'acc.wrong':>9s}")
    for name, p in rep["policies"].items():
        out.append(f"  {name:22s} {_ci(p['resolved'], p['n'], p['ci95']):>20s} {p['cloud_calls']:>6d} "
                   f"{p['local_s']:>9.0f} {p['over_route']:>5d} {p['under_route']:>6d} {p['accepted_wrong']:>9d}")
    out.append("\ndeterministic labels from the prompt alone: " + ", ".join(
        f"{lab} {len(ks)}" for lab, ks in rep["labels"].items()))
    named = {lab: ks for lab, ks in rep["labels"].items() if lab != "none"}
    if named:
        out.append("  no deterministic executor run is stored, so these are unmeasured: " + "; ".join(
            f"{lab}: {', '.join(ks)}" for lab, ks in named.items()))
    return "\n".join(out)


def run(runs: dict, *, store=None, cases_dir=None) -> dict:
    """The routing report for stored runs {route: run id}, read with SQLite mode=ro."""
    from evals.core import load_cases
    from evals.importers import CASES
    from harness import live_audit
    from harness import memory_store as ms
    conn = live_audit.open_readonly(Path(store) if store else ms.db_path())
    try:
        by = {r: load(conn, i) for r, i in runs.items() if i}
    finally:
        conn.close()
    meta = {c.id: (c.prompt, (c.params or {}).get("variant") or "")
            for c in load_cases(Path(cases_dir) if cases_dir else CASES / "repo")}
    return report(by, meta, {r: i for r, i in runs.items() if i})
