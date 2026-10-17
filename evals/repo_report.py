"""Repo-lane report over stored runs, with the task as the unit of analysis. #923.

    soh repo-report RUN [RUN] [--store PATH] [--cases DIR]

A task is one fix commit (params.fix); its spec and symptom variants share code,
fix and tests, so they are never counted as independent cases.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from evals import compare
from evals.importers.history import VARIANTS
from harness import intervals, paired, power, reasons

#: Per-failing-case lifts the tasks-needed line is printed for.
LIFTS = (0.1, 0.2, 0.3)
#: Classes that are a ceiling we chose, not the model's answer.
LIMIT_CLASSES = tuple(c for c, (_, r) in reasons.CLASSES.items() if r == reasons.LIMIT)
VIEWS = {"limits as losses": reasons.NEVER_RAN, "limits unjudged": reasons.NEVER_RAN + LIMIT_CLASSES}


class Refused(Exception):
    """The runs cannot be reported together; the message says why."""


def _alpha() -> float:
    from harness import adopt
    return adopt.ALPHA


def load(conn, run_ids) -> tuple[list[dict], list[dict]]:
    """(runs, result rows) for the given run ids from a store connection."""
    runs, rows = [], []
    for rid in run_ids:
        got = conn.execute("SELECT id, lane, repeat_count, cases_digest, receipt, environment, generated_at "
                           "FROM runs WHERE id = ?", (int(rid),)).fetchone()
        if got is None:
            raise Refused(f"no run {rid} in the store")
        rid, lane, repeat, digest, receipt, env, at = tuple(got)
        runs.append({"id": rid, "lane": lane, "repeat": repeat, "cases_digest": digest,
                     "receipt": json.loads(receipt or "{}"), "environment": json.loads(env or "{}"),
                     "generated_at": at})
        rows += [{"run_id": rid, "candidate": c, "case_id": k, "repeat_index": i, "passed": bool(p),
                  "failure_class": fc or "", "hit_limit": hl or ""}
                 for c, k, i, p, fc, hl in conn.execute(
                     "SELECT candidate, case_id, repeat_index, passed, failure_class, hit_limit "
                     "FROM results WHERE run_id = ? ORDER BY seq", (rid,))]
    return runs, rows


def check_runs(runs: list[dict], cases) -> None:
    """Refuse runs that are not one repo exam, or whose cases differ from the local files the task keys come from."""
    from evals.core import cases_digest
    if not runs:
        raise Refused("no runs given")
    for r in runs:
        if (r["receipt"].get("modality") or r["lane"]) != "repo":
            raise Refused(f"run {r['id']} is not a repo-lane run")
    digests = {r["cases_digest"] for r in runs}
    if len(digests) > 1:
        raise Refused("the runs ran different case sets: " + ", ".join(
            f"run {r['id']} {r['cases_digest']}" for r in runs))
    by_id = {c.id: c for c in cases}
    for r in runs:
        ids = r["receipt"].get("case_ids") or []
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise Refused(f"run {r['id']} ran cases with no local file: {', '.join(missing)}")
        if ids and cases_digest([by_id[i] for i in ids]) != r["cases_digest"]:
            raise Refused(f"run {r['id']}'s cases differ from the local case files, so their task keys "
                          f"are not the ones that ran")


def tasks_of(cases) -> dict[str, tuple[str, str]]:
    """case id -> (task key, variant). The key is params.fix, never the case name."""
    out = {}
    for c in cases:
        params = c.params or {}
        if params.get("fix") and params.get("variant") in VARIANTS:
            out[c.id] = (str(params["fix"]), params["variant"])
    return out


def labels(task: dict) -> dict[str, str]:
    """task key -> a name to print: its case ids' common prefix, or the fix sha when they share none."""
    import os
    ids: dict = {}
    for k, (t, _) in task.items():
        ids.setdefault(t, []).append(k)
    out = {}
    for t, ks in ids.items():
        pre = os.path.commonprefix(ks)
        if any(k != pre for k in ks):
            pre = pre[:max(pre.rfind("-"), pre.rfind("_"), 0)]
        out[t] = pre.rstrip("-_") or t[:12]
    return out


def _draws(rows, candidates) -> dict:
    """case -> candidate -> [(passed, failure_class)] in repeat order."""
    from harness import holdout
    out: dict = {}
    for r in sorted(rows, key=lambda r: r.get("repeat_index") or 1):
        if r["candidate"] in candidates:
            out.setdefault(holdout.base_id(r["case_id"]), {}).setdefault(r["candidate"], []).append(
                (bool(r["passed"]), r.get("failure_class") or ""))
    return out


def _rate(k: int, n: int) -> dict:
    return {"resolved": k, "n": n, "rate": round(k / n, 4) if n else 0.0, "ci95": list(intervals.wilson(k, n))}


def _verdict(lo: int, hi: int, alpha: float) -> dict:
    d = lo + hi
    p = paired.sign_test(min(lo, hi), d)
    testable = paired.sign_test(0, d) <= alpha
    word = (f"untestable at {d} discordant" if not testable
            else "differs" if p <= alpha else "no evidence")
    return {"discordant": d, "p": round(p, 4), "testable": testable, "verdict": word}


def _view(draws: dict, task: dict, candidates: list[str], skip, *, alpha, resamples, seed) -> dict:
    base, cand = candidates
    cases = sorted(k for k in draws if not any(fc in skip for d in draws[k].values() for _, fc in d))
    by = {c: {k: (sum(p for p, _ in draws[k][c]), len(draws[k][c])) for k in cases} for c in candidates}
    rates = {}
    for c in candidates:
        mine = {"all": _rate(sum(by[c][k][0] for k in cases), sum(by[c][k][1] for k in cases))}
        for v in VARIANTS:
            ks = [k for k in cases if task[k][1] == v]
            mine[v] = _rate(sum(by[c][k][0] for k in ks), sum(by[c][k][1] for k in ks))
        rates[c] = mine
    keys = sorted({task[k][0] for k in cases})
    solved = {c: {t: any(by[c][k][0] for k in cases if task[k][0] == t) for t in keys} for c in candidates}
    only = {c: [t for t in keys if solved[c][t] and not solved[o][t]] for c, o in (candidates, candidates[::-1])}
    both = [t for t in keys if solved[base][t] and solved[cand][t]]
    out = {"cases": len(cases), "tasks": len(keys), "rates": rates,
           "tasks_resolved": {c: sum(solved[c].values()) for c in candidates},
           "only": only, "both": both, **_verdict(len(only[cand]), len(only[base]), alpha)}
    if cases:
        iv = compare.interval(by, cases, cand, base, resamples=resamples, seed=seed,
                              clusters={k: task[k][0] for k in cases})
        out["difference"] = {k: round(iv[k], 4) for k in ("difference", "low", "high")}
    out["gap"] = {c: _gap(by[c], cases, task, alpha=alpha, resamples=resamples, seed=seed) for c in candidates}
    out["power"] = {c: _power(by[c], cases, task, [r for k in cases for r in _as_rows(draws[k][c], c, k)],
                              c, alpha) for c in candidates}
    return out


def _as_rows(draws, candidate, case):
    return [{"candidate": candidate, "case_id": case if i == 0 else f"{case}#{i + 1}", "passed": p}
            for i, (p, _) in enumerate(draws)]


def _gap(by: dict, cases, task, *, alpha, resamples, seed) -> dict:
    """Spec minus symptom within one candidate, over tasks that kept both variants."""
    per: dict = {}
    for k in cases:
        per.setdefault(task[k][0], {})[task[k][1]] = by[k]
    keys = sorted(t for t, v in per.items() if set(v) == set(VARIANTS))
    spec_only = [t for t in keys if per[t]["spec"][0] and not per[t]["symptom"][0]]
    symptom_only = [t for t in keys if per[t]["symptom"][0] and not per[t]["spec"][0]]
    out = {"tasks": len(keys), "spec_only": spec_only, "symptom_only": symptom_only,
           **_verdict(len(spec_only), len(symptom_only), alpha)}
    if out["testable"]:
        iv = compare.interval({v: {t: per[t][v] for t in keys} for v in VARIANTS}, keys, "spec", "symptom",
                              resamples=resamples, seed=seed)
        out["difference"] = {k: round(iv[k], 4) for k in ("difference", "low", "high")}
    return out


def _power(by: dict, cases, task, rows, candidate, alpha) -> dict:
    """Tasks needed per variant base, from power.py; the effect is a per-failing-case lift q = min(1, p + d)."""
    rho, repeat = power.rows_icc(rows, [candidate])
    measured = rho is not None
    use = rho if measured else power.DEFAULT_RHO
    out = {"rho": None if rho is None else round(rho, 4), "rho_measured": measured, "rho_used": use,
           "repeat": round(repeat, 2)}
    for v in VARIANTS:
        rates = [by[k][0] / by[k][1] for k in cases if task[k][1] == v and by[k][1]]
        out[v] = {"tasks": len(rates),
                  "needed": {str(e): power.cases_needed(rates, e, rho=use, stochastic=measured, alpha=alpha)
                             for e in LIFTS},
                  "mde": power.mde(rates, 1, alpha, use, power.TARGET) if rates else None}
    return out


def _config(r: dict) -> dict:
    rec, env = r["receipt"], r["environment"]
    at = r.get("generated_at")
    return {"run": r["id"], "repeat": rec.get("repeat", r.get("repeat")), "max_tokens": rec.get("max_tokens"),
            "sampling": (rec.get("sampling") or {}).get("repo"), "git_sha": env.get("git_sha"),
            "git_dirty": env.get("git_dirty"), "machine": rec.get("machine") or env.get("fingerprint"),
            "cases_digest": r["cases_digest"], "engines": rec.get("engines") or {}, "served": rec.get("served") or {},
            "instruments": rec.get("instruments") or {}, "pressure": rec.get("pressure") or {},
            "generated_at": datetime.datetime.fromtimestamp(at, datetime.timezone.utc).isoformat(timespec="seconds")
            if at else None}


def report(runs: list[dict], rows: list[dict], cases, *, resamples: int = compare.DEFAULT_RESAMPLES,
           seed: int = 1) -> dict:
    """Everything the text prints, as data. The first run's candidate is the baseline."""
    alpha = _alpha()
    order = []
    for r in runs:
        for row in rows:
            if row["run_id"] == r["id"] and row["candidate"] not in order:
                order.append(row["candidate"])
    if len(order) != 2:
        raise Refused(f"a repo report compares two candidates; these runs hold {len(order)}: {', '.join(order)}")
    task = tasks_of(cases)
    draws = _draws(rows, order)
    no_key = sorted(k for k in draws if k not in task)
    unpaired = sorted(k for k in draws if k in task and set(draws[k]) != set(order))
    variants: dict = {}
    for k in draws:
        if k in task and k not in unpaired:
            variants.setdefault(task[k][0], set()).add(task[k][1])
    single = sorted(k for k in draws if k in task and k not in unpaired and variants[task[k][0]] != set(VARIANTS))
    suite = {k: d for k, d in draws.items() if k in task and k not in unpaired and k not in single}
    never_ran = sorted(k for k, d in suite.items() if any(fc in reasons.NEVER_RAN for x in d.values() for _, fc in x))
    limits = {c: sum(fc in LIMIT_CLASSES for k in suite if k not in never_ran for _, fc in suite[k][c])
              for c in order}
    return {"baseline": order[0], "candidate": order[1], "alpha": alpha, "runs": [{**_config(r), "candidates": [c for c in order if any(
                row["run_id"] == r["id"] and row["candidate"] == c for row in rows)]} for r in runs],
            "labels": labels({k: task[k] for k in suite}),
            "differ_on": [a for a in paired.AXES + ("engines",)
                          if len(runs) == 2 and runs[0]["receipt"].get(a) != runs[1]["receipt"].get(a)],
            "set_aside": {"no_task_key": no_key, "unpaired": unpaired, "single_variant": single},
            "excluded_never_ran": never_ran, "limit_rows": limits,
            "views": {name: _view(suite, task, order, skip, alpha=alpha, resamples=resamples, seed=seed)
                      for name, skip in VIEWS.items()}}


def _ci(x: dict) -> str:
    return f"{x['resolved']}/{x['n']} [{x['ci95'][0]:.2f}, {x['ci95'][1]:.2f}]"


def text(rep: dict) -> str:
    base, cand = rep["baseline"], rep["candidate"]
    out = []
    for c in rep["runs"]:
        out.append(f"run {c['run']} ({', '.join(c['candidates'])}): repeat {c['repeat']}, max_tokens {c['max_tokens']}, sampling {c['sampling']}, "
                   f"git {c['git_sha']}{' dirty' if c['git_dirty'] else ''}, {c['machine']}, cases {c['cases_digest']}, "
                   f"at {c['generated_at']}")
        out.append(f"  engines {c['engines'] or 'none recorded'}, served {c['served'] or 'none recorded'}, "
                   f"free memory {c['pressure'].get('free_pct', '?')}%")
    if rep["differ_on"]:
        out.append(f"the two runs also differ on: {', '.join(rep['differ_on'])}")
    for why, ids in rep["set_aside"].items():
        if ids:
            out.append(f"set aside ({why.replace('_', ' ')}): {', '.join(ids)}")
    out.append(f"excluded, harness never ran ({len(rep['excluded_never_ran'])}): "
               f"{', '.join(rep['excluded_never_ran']) or 'none'}")
    for name, v in rep["views"].items():
        out.append(f"\n{name}: {v['cases']} cases from {v['tasks']} tasks; a task is resolved when either variant is")
        out.append(f"  {'candidate':40s} {'all':>18s} {'spec':>18s} {'symptom':>18s} {'tasks':>6s}"
                   + (f" {'LIMIT':>6s}" if name == "limits as losses" else ""))
        for c in (base, cand):
            r = v["rates"][c]
            out.append(f"  {c:40.40s} {_ci(r['all']):>18s} {_ci(r['spec']):>18s} {_ci(r['symptom']):>18s} "
                       f"{v['tasks_resolved'][c]:>6d}" + (f" {rep['limit_rows'][c]:>6d}" if name == "limits as losses"
                                                          else ""))
        name_of = rep["labels"]
        out.append(f"  tasks: {cand} only {_named(v['only'][cand], name_of)}, {base} only "
                   f"{_named(v['only'][base], name_of)}, both {_named(v['both'], name_of)}; "
                   f"exact sign p = {v['p']}: {v['verdict']}")
        if "difference" in v:
            d = v["difference"]
            out.append(f"  case resolve rate {cand} minus {base}: {d['difference']:+.3f}, 95% task bootstrap "
                       f"[{d['low']:+.3f}, {d['high']:+.3f}] (descriptive; the sign test is the verdict)")
        for c in (base, cand):
            g = v["gap"][c]
            line = (f"  spec minus symptom, {c}: spec only {_named(g['spec_only'], name_of)}, symptom only "
                    f"{_named(g['symptom_only'], name_of)} of {g['tasks']} tasks: {g['verdict']}")
            if g["testable"]:
                line += f", p = {g['p']}"
                if "difference" in g:
                    line += f", {g['difference']['difference']:+.3f} [{g['difference']['low']:+.3f}, {g['difference']['high']:+.3f}]"
            out.append(line)
    v = rep["views"]["limits as losses"]
    out.append(f"\npower (limits as losses, alpha {rep['alpha']}, target {power.TARGET}); effect is a per-failing-case "
               f"lift q = min(1, p + d), not a resolve-rate difference")
    for c in (base, cand):
        pw = v["power"][c]
        rho = f"rho {pw['rho']}" if pw["rho_measured"] else f"rho unmeasured (repeat {pw['repeat']}), {pw['rho_used']} used"
        for var in VARIANTS:
            p = pw[var]
            need = " / ".join(str(p["needed"][str(e)]) for e in LIFTS)
            out.append(f"  {c:40.40s} {var:8s} base: tasks needed {need} for lifts "
                       f"{' / '.join(map(str, LIFTS))}; MDE at {p['tasks']} tasks {p['mde']}; {rho}")
    return "\n".join(out)


def _named(keys, name_of) -> str:
    return f"{len(keys)}" + (f" ({', '.join(sorted(name_of.get(k, k[:12]) for k in keys))})" if keys else "")


def run(run_ids, *, store=None, cases_dir=None, resamples: int = compare.DEFAULT_RESAMPLES, seed: int = 1) -> dict:
    """The report for stored runs, read with SQLite mode=ro."""
    from evals.core import load_cases
    from evals.importers import CASES
    from harness import live_audit
    from harness import memory_store as ms
    conn = live_audit.open_readonly(Path(store) if store else ms.db_path())
    try:
        runs, rows = load(conn, run_ids)
    finally:
        conn.close()
    cases = load_cases(Path(cases_dir) if cases_dir else CASES / "repo")
    check_runs(runs, cases)
    return report(runs, rows, cases, resamples=resamples, seed=seed)
