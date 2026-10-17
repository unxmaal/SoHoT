"""Laya zero-shot on the decide cases, graded by the lane's own grader, beside a stored run over those case ids. #970.

    python -m evals.analysis.laya_decide run --python .venv-laya/bin/python --out DIR [--run 462]

`predict` is the only step that imports Laya; it runs under Laya's own venv with `python -I`,
so this module imports nothing outside the standard library at the top.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

LAYA_REPO = "convaiinnovations/laya"
LAYA_REV = "7b928d828b7b0e022f929d9bd2e44165aa270148"
#: The stored Imajev-4B decide run on the 476-case set (cases_digest e1031939e7098172).
DEFAULT_RUN = 462
SHUFFLE_SEED = 970


def _field_question(case_id: str, name: str, spec: dict, seed: int | None) -> dict:
    description = str(spec["description"]).strip()
    if spec["type"] == "boolean":
        return {"type": "noul", "instructions": description}
    values = [str(c) for c in spec["choices"]]
    if seed is not None:
        random.Random(f"{seed}:{case_id}:{name}").shuffle(values)
    notes = spec.get("choice_descriptions") or {}
    return {"type": "choice", "instructions": description,
            "criteria": {v: str(notes.get(v) or "") for v in values}}


def questions(case_id: str, schema: dict, seed: int | None = None) -> dict:
    """One Laya question per decide field: noul for a boolean, choice for an enum, options shuffled when seeded."""
    return {name: _field_question(case_id, name, spec, seed) for name, spec in schema.items()}


def state(case) -> str:
    """What the case asks about, without the lettered reply format load_case appends for text models."""
    from harness.checks import decide
    prompt = case.prompt.removesuffix(f"\n\n{decide.render(case.params['schema'])}")
    return f"{prompt.strip()}\n\n{case.context}".strip()


def export(cases, seed: int | None = None) -> list[dict]:
    return [{"id": c.id, "state": state(c), "questions": questions(c.id, c.params["schema"], seed)}
            for c in cases]


def artifact(answers: dict, schema: dict) -> dict:
    """Laya's answers in the canonical shape decide.check grades: an answer and a distribution per field."""
    out, probs = {}, {}
    for name, spec in schema.items():
        got = answers.get(name) or {}
        if spec["type"] == "boolean" and "noul" in got:
            p = float(got["noul"])
            probs[name] = {"true": p, "false": 1.0 - p}
            out[name] = "true" if p >= 0.5 else "false"
        elif got.get("probabilities"):
            probs[name] = {str(k): float(v) for k, v in got["probabilities"].items()}
            out[name] = str(got.get("choice"))
    return {"answers": out, "probabilities": probs}


def predict(rows: list[dict], agent, clock=time.perf_counter) -> list[dict]:
    """Every row through agent.system_one, one case per call, after one untimed warm-up call."""
    if rows:
        agent.system_one(rows[0]["state"], rows[0]["questions"])
    out = []
    for row in rows:
        started = clock()
        got = agent.system_one(row["state"], row["questions"])
        out.append({"id": row["id"], "seconds": clock() - started,
                    "answers": got.get("answers") or {}, "usage": got.get("usage") or {}})
    return out


def _predict_main(args) -> int:
    import laya
    agent = laya.load(args.model, device=args.device)
    rows = [json.loads(line) for line in Path(args.inp).read_text(encoding="utf-8").splitlines() if line]
    with Path(args.dest).open("w", encoding="utf-8") as fh:
        for row in predict(rows, agent):
            fh.write(json.dumps(row) + "\n")
    return 0


def grade(cases, predictions: list[dict]) -> list[dict]:
    """Per case: decide.check's metrics on Laya's answers, plus seconds and whether the state was cut."""
    from harness.checks import decide
    by_id = {p["id"]: p for p in predictions}
    rows = []
    for case in cases:
        pred = by_id.get(case.id)
        if pred is None:
            continue
        schema = case.params["schema"]
        result = decide.check(artifact(pred["answers"], schema), schema, case.assertions["answers"])
        usage = pred.get("usage") or {}
        rows.append({"id": case.id, "passed": bool(result.ok), "seconds": float(pred["seconds"]),
                     "truncated": bool(usage.get("truncated") or usage.get("truncated_questions")),
                     **result.metrics})
    return rows


def stored(conn, run_id: int) -> tuple[str, str, list[dict]]:
    """(candidate, cases_digest, per-case rows) of one stored decide run."""
    run = conn.execute("SELECT lane, cases_digest FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None or run["lane"] != "decide":
        raise SystemExit(f"run {run_id} is not a decide run in this store")
    rows, names = [], set()
    for r in conn.execute("SELECT candidate, case_id, passed, seconds, metrics FROM results "
                          "WHERE run_id = ? ORDER BY seq", (run_id,)):
        names.add(r["candidate"])
        rows.append({"id": r["case_id"], "passed": bool(r["passed"]), "seconds": float(r["seconds"] or 0.0),
                     "truncated": False, **json.loads(r["metrics"] or "{}")})
    if len(names) != 1:
        raise SystemExit(f"run {run_id} holds {len(names)} candidates; this report compares one")
    return names.pop(), run["cases_digest"], rows


def summarize(rows: list[dict]) -> dict:
    from harness import intervals
    from harness.checks import decide
    fields = sum(int(r.get("decide_fields", 0)) for r in rows)
    right = sum(int(r.get("decide_correct", 0)) for r in rows)
    exact = sum(1 for r in rows if r["passed"])
    calibrated = [r for r in rows if r.get("calibrated") == 1.0]
    brier_fields = sum(int(r["decide_fields"]) for r in calibrated)
    pairs = [(c, k) for r in calibrated for c, k in r.get("decisions", [])]
    seconds = [r["seconds"] for r in rows]
    return {"cases": len(rows), "fields": fields, "correct": right,
            "accuracy": right / fields if fields else 0.0, "accuracy_ci": intervals.wilson(right, fields),
            "exact": exact, "exact_ci": intervals.wilson(exact, len(rows)),
            "brier": sum(r["decide_brier_sum"] for r in calibrated) / brier_fields if brier_fields else None,
            "ece": decide.ece(pairs) if pairs else None,
            "s_median": statistics.median(seconds) if seconds else 0.0,
            "s_mean": statistics.fmean(seconds) if seconds else 0.0,
            "truncated": sum(1 for r in rows if r["truncated"])}


def flips(a: list[dict], b: list[dict], cases=None) -> dict:
    """Fields whose correctness differs between two gradings, and each side's correct count; enum fields only when cases are given."""
    kinds = {c.id: [s["type"] for s in c.params["schema"].values()] for c in cases or []}
    by_id = {r["id"]: r for r in b}
    out = {"changed": 0, "fields": 0, "a": 0, "b": 0}
    for r in a:
        other = by_id.get(r["id"])
        if other is None:
            continue
        types = kinds.get(r["id"])
        for i, ((_, x), (_, y)) in enumerate(zip(r.get("decisions", []), other.get("decisions", []))):
            if types is not None and types[i] != "enum":
                continue
            out["fields"] += 1
            out["changed"] += int(x != y)
            out["a"] += int(x)
            out["b"] += int(y)
    return out


def _control(c: dict) -> str:
    from harness import intervals
    n = c["fields"]
    a, b = intervals.wilson(c["a"], n), intervals.wilson(c["b"], n)
    return (f"negative control (options shuffled; only enum fields can move, a boolean is a noul question with a fixed "
            f"order): {c['changed']} of {n} enum verdicts change; enum accuracy ordered {c['a']}/{n} [{a[0]:.3f}, "
            f"{a[1]:.3f}], shuffled {c['b']}/{n} [{b[0]:.3f}, {b[1]:.3f}]")


def _fmt(label: str, s: dict) -> str:
    lo, hi = s["accuracy_ci"]
    elo, ehi = s["exact_ci"]
    brier = "-" if s["brier"] is None else f"{s['brier']:.3f}"
    ece = "-" if s["ece"] is None else f"{s['ece']:.3f}"
    return (f"| {label} | {s['correct']}/{s['fields']} {s['accuracy']:.3f} [{lo:.3f}, {hi:.3f}] "
            f"| {s['exact']}/{s['cases']} [{elo:.3f}, {ehi:.3f}] | {brier} | {ece} "
            f"| {s['s_median']:.3f} / {s['s_mean']:.3f} | {s['truncated']} |")


def family(case_id: str) -> str:
    return case_id.rsplit("-", 1)[0]


def majority(cases) -> list[dict]:
    """A constant responder: each field answered with its most common gold across the family, in sample."""
    from collections import Counter

    from harness.checks import decide
    common: dict[tuple[str, str], Counter] = {}
    for c in cases:
        for name, value in c.assertions["answers"].items():
            common.setdefault((family(c.id), name), Counter())[decide.key(value)] += 1
    rows = []
    for c in cases:
        schema = c.params["schema"]
        answers = {n: common[(family(c.id), n)].most_common(1)[0][0] for n in schema}
        result = decide.check({"answers": answers}, schema, c.assertions["answers"])
        rows.append({"id": c.id, "passed": bool(result.ok), "seconds": 0.0, "truncated": False, **result.metrics})
    return rows


def _families(arms: list[tuple[str, list[dict]]]) -> list[str]:
    names = sorted({family(r["id"]) for _, rows in arms for r in rows})
    out = ["", "| arm | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for label, rows in arms:
        cells = []
        for name in names:
            mine = [r for r in rows if family(r["id"]) == name]
            k, n = sum(r["decide_correct"] for r in mine), sum(r["decide_fields"] for r in mine)
            cells.append(f"{k}/{n} {k / n:.3f}" if n else "-")
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return out


def report(arms: list[tuple[str, list[dict]]], digest: str, stored_digest: str | None,
           control: dict | None = None) -> str:
    lines = [f"cases_digest {digest}" + ("" if stored_digest is None else
             f"; stored run's {stored_digest} ({'same case set' if stored_digest == digest else 'DIFFERENT case set'})"),
             "", "| arm | field accuracy [95% Wilson] | exact cases [95% Wilson] | Brier | ECE "
             "| s/case median / mean | states cut |", "|---|---|---|---|---|---|---|"]
    lines += [_fmt(label, summarize(rows)) for label, rows in arms]
    lines += _families(arms)
    if control is not None:
        lines += ["", _control(control)]
    return "\n".join(lines)


def _store(path: str):
    from harness import live_audit
    from harness import memory_store as ms
    return live_audit.open_readonly(Path(path) if path else ms.db_path())


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def run_predictor(python: str, model: str, device: str, inp: Path, dest: Path) -> None:
    subprocess.run([python, "-I", str(Path(__file__).resolve()), "predict", "--in", str(inp),
                    "--out", str(dest), "--model", model, "--device", device], check=True)


def run(cases_dir: Path, out: Path, store: str, run_id: int | None, predictor, shuffle: bool = True) -> str:
    from evals import core
    cases = core.load_cases(cases_dir)
    digest = core.cases_digest(cases)[:16]
    out.mkdir(parents=True, exist_ok=True)
    passes = [("ordered", None)] + ([("shuffled", SHUFFLE_SEED)] if shuffle else [])
    graded = {}
    for name, seed in passes:
        inp, dest = out / f"{name}.in.jsonl", out / f"{name}.pred.jsonl"
        _write(inp, export(cases, seed))
        if not dest.exists():
            predictor(inp, dest)
        graded[name] = grade(cases, _read(dest))
    arms = [("Laya (convaiinnovations/laya, zero-shot)", graded["ordered"])]
    if "shuffled" in graded:
        arms.append(("Laya, options shuffled", graded["shuffled"]))
    stored_digest = None
    if run_id is not None:
        candidate, stored_digest, rows = stored(_store(store), run_id)
        ids = {r["id"] for r in graded["ordered"]}
        arms.append((f"{candidate} (run {run_id})", [r for r in rows if r["id"] in ids]))
    arms.append(("majority answer per field (in-sample)", majority(cases)))
    control = flips(graded["ordered"], graded["shuffled"], cases) if "shuffled" in graded else None
    return report(arms, digest, stored_digest, control)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.analysis.laya_decide", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict", help="run Laya over an exported case file (inside Laya's venv)")
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", dest="dest", required=True)
    p.add_argument("--model", required=True, help="a local checkpoint directory")
    p.add_argument("--device", default="mps")
    r = sub.add_parser("run", help="export, predict (ordered and shuffled), grade and compare")
    r.add_argument("--python", required=True, help="Laya venv's python")
    r.add_argument("--model", required=True, help=f"local snapshot of {LAYA_REPO}@{LAYA_REV}")
    r.add_argument("--device", default="mps")
    r.add_argument("--out", required=True, help="directory for the exported cases and predictions")
    r.add_argument("--cases", default=str(Path(__file__).resolve().parents[1] / "cases" / "decide"))
    r.add_argument("--store", default="", help="store to read the comparison run from, read-only")
    r.add_argument("--run", type=int, default=DEFAULT_RUN, help="stored decide run to compare; 0 for none")
    r.add_argument("--no-shuffle", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "predict":
        return _predict_main(args)
    print(run(Path(args.cases), Path(args.out), args.store, args.run or None,
              lambda inp, dest: run_predictor(args.python, args.model, args.device, inp, dest),
              shuffle=not args.no_shuffle))
    return 0


if __name__ == "__main__":
    sys.exit(main())
