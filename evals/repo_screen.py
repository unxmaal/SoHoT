"""The repo exam's screening subset: a fixed, stratified draw of its cases, and the verdict over screen runs. #1176."""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path

from harness import holdout

LANE = "repo"
#: Cases the screening subset draws from the repo exam.
CASES = 24
#: Independent third-party benchmarks ranking a candidate above the base before a failed screen is rerun.
OUTSIDE_VOTES = 3
#: Reruns of a failed screen when outside evidence disagrees with it; the verdict pools every draw.
REPEATS = 3
#: Mixed into each case id's hash so the order within a stratum is fixed and not alphabetical.
SEED = 1176
#: Per-case outcomes of the two runs the anchor classes come from, committed so the draw is fixed.
ANCHORS = Path(__file__).resolve().parent / "cases" / "repo" / "screen_anchors.json"
#: Within a stratum, cases sort by class in this order before the systematic draw.
CLASSES = ("base_pass", "reference_only", "neither", "unseen")


class Refused(Exception):
    """The screen cannot be drawn or judged; the message says why."""


def group_of(case) -> str:
    """The importer group a repo case came from: its directory under the repo cases."""
    src = getattr(case, "source", None)
    return Path(src).parent.name if src else (case.modality or "")


def variant_of(case) -> str:
    return str((case.params or {}).get("variant") or "case")


def stratum_of(case) -> tuple[str, str]:
    return group_of(case), variant_of(case)


def task_key(case) -> str:
    return holdout.task_of(case) or case.id


def load_anchors(path: Path | None = None) -> dict:
    p = Path(path) if path else ANCHORS
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def class_of(case_id: str, anchors: dict) -> str:
    base = (anchors.get("base") or {}).get("passed") or {}
    ref = (anchors.get("reference") or {}).get("passed") or {}
    if case_id not in base or case_id not in ref:
        return "unseen"
    if base[case_id]:
        return "base_pass"
    return "reference_only" if ref[case_id] else "neither"


def _hash(case_id: str) -> str:
    return hashlib.sha256(f"{SEED}\0{case_id}".encode("utf-8")).hexdigest()


def allocate(sizes: dict, n: int) -> dict:
    """Cases per stratum: one each, the rest in proportion to what each has left, largest remainder first."""
    keys = sorted(sizes)
    total = sum(sizes.values())
    if n >= total:
        return dict(sizes)
    if n < len(keys):
        raise Refused(f"{n} screen cases cannot cover the {len(keys)} strata "
                      f"({', '.join('/'.join(k) for k in keys)})")
    rest = n - len(keys)
    spare = {k: sizes[k] - 1 for k in keys}
    pool = sum(spare.values())
    quota = {k: rest * spare[k] / pool if pool else 0.0 for k in keys}
    got = {k: 1 + int(quota[k]) for k in keys}
    left = n - sum(got.values())
    for k in sorted(keys, key=lambda k: (-(quota[k] - int(quota[k])), k))[:left]:
        got[k] += 1
    return got


def _ordered(cases, anchors: dict) -> list:
    rank = {c: i for i, c in enumerate(CLASSES)}
    return sorted(cases, key=lambda c: (rank[class_of(c.id, anchors)], _hash(c.id)))


def pick(cases, n: int | None = None, anchors: dict | None = None) -> list:
    """The screening subset: every stratum (group x variant) covered, a systematic draw over class-sorted cases within each, one case per task where the stratum allows."""
    n = int(CASES if n is None else n)
    anchors = load_anchors() if anchors is None else anchors
    by: dict = {}
    for c in cases:
        by.setdefault(stratum_of(c), []).append(c)
    if not by:
        raise Refused("no repo cases to draw a screen from")
    alloc = allocate({k: len(v) for k, v in by.items()}, n)
    chosen, tasks = [], set()
    for key in sorted(by):
        order = _ordered(by[key], anchors)
        size, k = len(order), alloc[key]
        taken: set = set()
        for i in range(k):
            at = int((i + 0.5) * size / k)
            cls = class_of(order[at].id, anchors)
            alt = [j for j in [*range(at, size), *range(at)] if j not in taken and class_of(order[j].id, anchors) == cls
                   and task_key(order[j]) not in tasks]
            j = alt[0] if alt else next(j for j in [at, *range(size)] if j not in taken)
            taken.add(j)
            tasks.add(task_key(order[j]))
            chosen.append(order[j])
    return sorted(chosen, key=lambda c: c.id)


def describe(cases, chosen, anchors: dict) -> dict:
    """The draw as data: per stratum how many cases it has and took, and the anchor classes taken."""
    from evals.core import cases_digest
    ids = {c.id for c in chosen}
    strata: dict = {}
    for c in cases:
        s = strata.setdefault("/".join(stratum_of(c)), {"cases": 0, "picked": []})
        s["cases"] += 1
        if c.id in ids:
            s["picked"].append(c.id)
    classes: dict = {}
    for c in chosen:
        classes[class_of(c.id, anchors)] = classes.get(class_of(c.id, anchors), 0) + 1
    base = (anchors.get("base") or {}).get("passed") or {}
    ref = (anchors.get("reference") or {}).get("passed") or {}
    return {"n": len(chosen), "of": len(cases), "digest": cases_digest(chosen), "strata": strata,
            "classes": classes, "tasks": len({task_key(c) for c in chosen}),
            "base": {"run": (anchors.get("base") or {}).get("run"), "passed": sum(bool(base.get(i)) for i in ids)},
            "reference": {"run": (anchors.get("reference") or {}).get("run"),
                          "passed": sum(bool(ref.get(i)) for i in ids)},
            "case_ids": sorted(ids)}


def anchors_from(runs: list[dict], rows: list[dict]) -> dict:
    """The anchors file's content from a base run and a reference run, first draw of each case."""
    if len(runs) != 2:
        raise Refused("anchors take two runs: the base, then the reference")
    out = {"seed": SEED}
    for side, r in zip(("base", "reference"), runs):
        got = {}
        cands = set()
        for row in sorted(rows, key=lambda x: x.get("repeat_index") or 1):
            if row["run_id"] == r["id"]:
                cands.add(row["candidate"])
                got.setdefault(holdout.base_id(row["case_id"]), bool(row["passed"]))
        if len(cands) != 1:
            raise Refused(f"run {r['id']} holds {len(cands)} candidates; an anchor run holds one")
        out[side] = {"run": r["id"], "candidate": next(iter(cands)), "passed": dict(sorted(got.items()))}
    return out


def _speed(rows) -> dict:
    secs = [r["seconds"] for r in rows if r.get("seconds") is not None]
    tps = [(r.get("metrics") or {}).get("tokens_per_s") for r in rows]
    tps = [t for t in tps if t]
    return {"median_s": round(statistics.median(secs), 1) if secs else None,
            "tokens_per_s": round(statistics.median(tps), 1) if tps else None}


def verdict(base_rows: list[dict], cand_rows: list[dict], cases, *, outside_votes: int = 0,
            n_votes: int | None = None, n_repeats: int | None = None) -> dict:
    """Task-level paired screen verdict of a candidate's pooled draws against the base on the subset they ran."""
    from evals import repo_report
    from harness import paired
    need_votes = OUTSIDE_VOTES if n_votes is None else n_votes
    repeats = REPEATS if n_repeats is None else n_repeats
    by_id = {c.id: c for c in cases}
    ran = {holdout.base_id(r["case_id"]) for r in cand_rows}
    missing = sorted(ran - set(by_id))
    if missing:
        raise Refused(f"the screen ran cases with no local file: {', '.join(missing)}")
    base_ids = {holdout.base_id(r["case_id"]) for r in base_rows}
    unpaired = sorted(ran - base_ids)
    if unpaired:
        raise Refused(f"the base run has no row for: {', '.join(unpaired)}")
    cands = {r["candidate"] for r in cand_rows}
    if len(cands) != 1:
        raise Refused(f"a screen verdict judges one candidate; the runs hold {', '.join(sorted(cands)) or 'none'}")
    task = {k: (task_key(by_id[k]), variant_of(by_id[k])) for k in ran}
    tally: dict = {"base": {}, "cand": {}}
    for side, rows in (("base", base_rows), ("cand", cand_rows)):
        for r in rows:
            k = holdout.base_id(r["case_id"])
            if k in ran:
                t = tally[side].setdefault(k, [0, 0])
                t[0] += bool(r["passed"])
                t[1] += 1
    draws = min(n for _, n in tally["cand"].values())
    wins = repo_report.task_wins({"base": tally["base"], "cand": tally["cand"]}, sorted(ran), task, "base", "cand")
    w, lost = len(wins["cand"]), len(wins["base"])
    p = paired.sign_test(min(w, lost), w + lost)
    favoured = outside_votes >= need_votes
    beats = w > lost
    if beats:
        state, why = "survives", f"wins {w} tasks, loses {lost}: measure it on the full exam"
    elif favoured and draws < 1 + repeats:
        state, why = "rerun", (f"{outside_votes} outside benchmarks rank it above the base (>= {need_votes}); "
                               f"pool {1 + repeats - draws} more draw(s) before declining: evals.run --modality repo "
                               f"--repo-screen --repeat {1 + repeats - draws}")
    elif favoured and lost <= w:
        state, why = "survives", f"tied on {draws} pooled draws ({w} vs {lost}), not below the base: measure it"
    else:
        state, why = "declined", f"wins {w} tasks, loses {lost} on {draws} draw(s)"
        from harness import cuts
        if favoured:
            why += ("; outside evidence disagrees, so record this as a finding about the exam "
                    "(single shot, no tools: #922, #890)")
            cuts.cut("screen_repeats", f"{next(iter(cands))} declined after its repo screen reruns", value=repeats,
                     kept=draws, dropped=1)
        elif outside_votes:
            cuts.cut("screen_outside_votes", f"{next(iter(cands))} declined with {outside_votes} outside votes",
                     value=need_votes, dropped=1)
    base_cases = [r for r in base_rows if holdout.base_id(r["case_id"]) in ran]
    return {"candidate": next(iter(cands)), "cases": len(ran), "tasks": len({task[k][0] for k in ran}),
            "draws": draws, "passed": sum(t[0] for t in tally["cand"].values()),
            "rows": sum(t[1] for t in tally["cand"].values()),
            "base_passed": sum(t[0] for t in tally["base"].values()),
            "base_rows": sum(t[1] for t in tally["base"].values()),
            "task_wins": w, "task_losses": lost, "sign_p": round(p, 4),
            "outside_votes": outside_votes, "votes_needed": need_votes, "repeats": repeats,
            "speed": _speed(cand_rows), "base_speed": _speed(base_cases), "verdict": state, "why": why}


def stored(conn, spec: str, ids) -> list[dict]:
    """The candidate's patch-harness repo rows on `ids`, pooled from every stored run that ran all of them. #1353."""
    from harness import reasons
    want = set(ids)
    out: list[dict] = []
    for run in conn.execute("SELECT id, specs, receipt FROM runs WHERE lane = ? ORDER BY id", (LANE,)):
        try:
            specs, receipt = json.loads(run["specs"] or "{}"), json.loads(run["receipt"] or "{}")
        except ValueError:
            continue
        keys = [k for k, v in specs.items() if spec in (k, v)]
        if not keys or (receipt.get("harness") or "patch") != "patch":
            continue
        got = []
        for r in conn.execute(f"SELECT case_id, passed, seconds, metrics, failure_class FROM results "
                              f"WHERE run_id = ? AND candidate IN ({','.join('?' * len(keys))})", (run["id"], *keys)):
            if holdout.base_id(r["case_id"]) not in want or (r["failure_class"] or "") in reasons.NEVER_RAN:
                continue
            try:
                metrics = json.loads(r["metrics"] or "{}")
            except ValueError:
                metrics = {}
            got.append({"case_id": r["case_id"], "candidate": spec, "passed": bool(r["passed"]),
                        "seconds": r["seconds"], "metrics": metrics if isinstance(metrics, dict) else {}})
        if {holdout.base_id(r["case_id"]) for r in got} >= want:
            out += got
    return out


def served() -> set:
    """The repo lane's served model by name and spec: reverify and knob sweeps rerun it, and it holds the lane already."""
    from harness import adopt, screen, winners
    name = adopt.default_for(LANE, winners.typed().get(LANE, ""))
    return {name, screen.candidate_for(LANE, name) or name} if name else set()


def refusal(conn, specs, cases, anchors: dict | None = None) -> str:
    """Why a repo exam larger than the screen waits for a spec's screen (none stored, or not survived), or "". #1353."""
    anchors = load_anchors() if anchors is None else anchors
    try:
        chosen = pick(cases, None, anchors)
    except Refused:
        return ""
    ids = [c.id for c in chosen]
    base = anchors.get("base") or {}
    passed = base.get("passed") or {}
    base_rows = [{"case_id": i, "candidate": base.get("candidate") or "base", "passed": bool(passed[i]),
                  "seconds": None} for i in ids if i in passed]
    anchored = {(anchors.get(side) or {}).get("candidate") for side in ("base", "reference")} | served()
    for spec in specs:
        if spec in anchored:
            continue
        rows = stored(conn, spec, ids)
        if not rows:
            return (f"{spec} has no repo screen result, so a full repo exam would spend hours on a question "
                    f"{len(ids)} cases can answer first: uv run python -m evals.run --modality repo "
                    f"--repo-screen --candidates {spec} --out <dir>, then soh repo-screen verdict <run>; "
                    f"--unscreened runs it anyway (#1353)")
        if len(base_rows) < len(ids):
            continue
        got = verdict(base_rows, rows, cases)
        if got["verdict"] != "survives":
            return (f"{spec}: its repo screen {got['verdict']} ({got['why']}), so a full repo exam waits; "
                    f"soh repo-screen verdict <runs> --outside-votes N weighs outside evidence; "
                    f"--unscreened runs it anyway (#1353)")
    return ""
