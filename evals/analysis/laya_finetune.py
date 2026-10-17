"""Laya fine-tuned on infovore's human relevance labels against bge-small plus logistic, on the same folds. #970.

    python -m evals.analysis.laya_finetune run --python .venv-laya/bin/python --model LAYA_SNAPSHOT \
        --embed-model BGE_SNAPSHOT --out DIR

`fit` imports torch, transformers and Laya and runs inside Laya's venv with `python -I`; the rest is stdlib.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: `infovore labels export --jsonl` as #311 ran it (488 labels, 46 held out).
LABELS = Path.home() / "infovore" / "exports" / "labels-2026-10-04.jsonl"
#: infovore.triage.embed.FOLD_SEED: the same folds the #311 embedding control used.
FOLD_SEED = "embed-cv-v1"
FOLDS = 5
MAX_CHARS = 2000
HEAD_ITERATIONS, HEAD_LEARNING_RATE, HEAD_L2 = 300, 0.01, 1.0
ARMS = ("embed", "laya-zs", "laya-ft")
QUESTION = {"relevant": {"type": "noul", "instructions": (
    "Is this chat exchange from a community Discord relevant? It is relevant if it touches technology, "
    "computers, SGI, IRIX or retrocomputing at all, however briefly, and irrelevant if it is off-topic chatter.")}}
GAINS = (0.10, 0.25, 0.50)
RESAMPLES = 2000


def load_labels(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return [{"id": int(r["id"]), "text": r["text"], "y": r["label"] == "relevant", "held_out": bool(r["held_out"]),
             "residue": r.get("cascade_stage") != "lexicon"} for r in rows]


def folds(items: list[dict], k: int = FOLDS) -> dict[int, int]:
    """infovore.triage.embed.stratified_folds over the items not held out."""
    assigned = {}
    for label in (True, False):
        members = sorted((r["id"] for r in items if r["y"] is label and not r["held_out"]),
                         key=lambda eid: hashlib.sha256(f"{FOLD_SEED}:{eid}".encode()).digest())
        for position, eid in enumerate(members):
            assigned[eid] = position % k
    return assigned


def splits(items: list[dict], assigned: dict[int, int], k: int = FOLDS) -> list[tuple[str, list[dict], list[dict]]]:
    """(name, train, test): one per fold over the trainable items, then the held-out items against all of them."""
    trainable = [r for r in items if not r["held_out"]]
    out = [(f"fold{f}", [r for r in trainable if assigned[r["id"]] != f],
            [r for r in trainable if assigned[r["id"]] == f]) for f in range(k)]
    out.append(("held", trainable, [r for r in items if r["held_out"]]))
    return out


def _blind(rows: list[dict]) -> list[dict]:
    return [{"id": r["id"], "text": r["text"]} for r in rows]


def fit_arm(items: list[dict], assigned: dict[int, int], fitter, dest: Path, k: int = FOLDS,
            clock=time.perf_counter) -> None:
    """Score every split's test items with fitter(train, blinded test) -> P(relevant); a split already in dest is kept."""
    done = {json.loads(line)["split"] for line in dest.read_text(encoding="utf-8").splitlines()} if dest.exists() else set()
    for name, train, test in splits(items, assigned, k):
        if name in done or not test:
            continue
        started = clock()
        scores = fitter(train, _blind(test))
        seconds = clock() - started
        with dest.open("a", encoding="utf-8") as fh:
            for row, p in zip(test, scores, strict=True):
                fh.write(json.dumps({"split": name, "id": row["id"], "p": float(p),
                                     "seconds": seconds / len(test)}) + "\n")


# ---- metrics, pure Python

def auc(ys: list[bool], ps: list[float]) -> float | None:
    """Mann-Whitney AUC with tied scores sharing their average rank."""
    pos = sum(1 for y in ys if y)
    neg = len(ys) - pos
    if not pos or not neg:
        return None
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    ranks = [0.0] * len(ps)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and ps[order[j + 1]] == ps[order[i]]:
            j += 1
        for m in range(i, j + 1):
            ranks[order[m]] = (i + j) / 2 + 1
        i = j + 1
    return (sum(r for r, y in zip(ranks, ys) if y) - pos * (pos + 1) / 2) / (pos * neg)


def _draws(n: int, resamples: int, seed: int):
    rng = random.Random(seed)
    for _ in range(resamples):
        yield [rng.randrange(n) for _ in range(n)]


def _percentile(xs: list[float]) -> tuple[float, float]:
    xs = sorted(xs)
    if not xs:
        return (float("nan"), float("nan"))
    return (xs[int(0.025 * (len(xs) - 1))], xs[int(math.ceil(0.975 * (len(xs) - 1)))])


def auc_ci(ys, ps, resamples=RESAMPLES, seed=970) -> tuple[float, float]:
    got = [a for idx in _draws(len(ys), resamples, seed)
           if (a := auc([ys[i] for i in idx], [ps[i] for i in idx])) is not None]
    return _percentile(got)


def paired_auc(ys, pa, pb, resamples=RESAMPLES, seed=970) -> dict:
    """AUC(a) - AUC(b) with a paired bootstrap over items; the verdict names a winner only when the interval excludes 0."""
    diffs = []
    for idx in _draws(len(ys), resamples, seed):
        y = [ys[i] for i in idx]
        a, b = auc(y, [pa[i] for i in idx]), auc(y, [pb[i] for i in idx])
        if a is not None and b is not None:
            diffs.append(a - b)
    lo, hi = _percentile(diffs)
    point = auc(ys, pa) - auc(ys, pb)
    verdict = "a better" if lo > 0 else "b better" if hi < 0 else "tie"
    return {"diff": point, "ci": (lo, hi), "verdict": verdict}


def brier(ys, ps) -> float:
    return sum((p - (1.0 if y else 0.0)) ** 2 for y, p in zip(ys, ps)) / len(ys)


def ece(ys, ps, bins: int = 10) -> float:
    pairs = [(max(p, 1 - p), (p >= 0.5) == y) for y, p in zip(ys, ps)]
    total = 0.0
    for b in range(bins):
        lo, hi = 0.5 + b * 0.5 / bins, 0.5 + (b + 1) * 0.5 / bins
        inside = [(c, k) for c, k in pairs if lo <= c < hi or (b == bins - 1 and c == 1.0)]
        if inside:
            total += len(inside) / len(pairs) * abs(sum(c for c, _ in inside) / len(inside)
                                                    - sum(k for _, k in inside) / len(inside))
    return total


def gain(ys, ps, share: float) -> float:
    """Share of the relevant items found in the top `share` of items by score."""
    order = sorted(range(len(ps)), key=lambda i: -ps[i])
    top = order[:math.ceil(share * len(ps))]
    pos = sum(1 for y in ys if y)
    return sum(1 for i in top if ys[i]) / pos if pos else 0.0


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def fit_temperature(ys, ps) -> float:
    """The temperature minimising log loss of sigmoid(logit / T), over a log grid from 0.05 to 20."""
    zs = [_logit(p) for p in ps]

    def nll(t):
        return -sum(math.log(max(_sigmoid(z / t) if y else 1 - _sigmoid(z / t), 1e-12)) for y, z in zip(ys, zs))
    grid = [math.exp(math.log(0.05) + i * (math.log(20) - math.log(0.05)) / 400) for i in range(401)]
    return min(grid, key=nll)


def calibrated(scores: dict[int, tuple[str, float]], labels: dict[int, bool]) -> dict[int, float]:
    """Each fold's scores divided by a temperature fitted on the other folds' scores; held-out items by one fitted on every fold."""
    out = {}
    for split in sorted({s for s, _ in scores.values()}):
        rest = [(labels[i], p) for i, (s, p) in scores.items() if s != split and s != "held"]
        t = fit_temperature([y for y, _ in rest], [p for _, p in rest]) if rest else 1.0
        for i, (s, p) in scores.items():
            if s == split:
                out[i] = _sigmoid(_logit(p) / t)
    return out


def read_scores(path: Path) -> dict[int, tuple[str, float, float]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {int(r["id"]): (r["split"], float(r["p"]), float(r["seconds"])) for r in rows}


def summarize(items: list[dict], scores: dict, resamples: int = RESAMPLES) -> dict:
    labels = {r["id"]: r["y"] for r in items}
    cal = calibrated({i: (s, p) for i, (s, p, _) in scores.items()}, labels)
    out = {}
    for pop, keep in (("all", lambda r: True), ("held out", lambda r: r["held_out"]),
                      ("residue", lambda r: r["residue"])):
        rows = [r for r in items if keep(r) and r["id"] in scores]
        ys = [r["y"] for r in rows]
        ps = [scores[r["id"]][1] for r in rows]
        cs = [cal[r["id"]] for r in rows]
        if not rows:
            continue
        out[pop] = {"n": len(rows), "pos": sum(ys), "auc": auc(ys, ps), "auc_ci": auc_ci(ys, ps, resamples),
                    "brier": brier(ys, ps), "ece": ece(ys, ps), "brier_t": brier(ys, cs), "ece_t": ece(ys, cs),
                    "gain": [gain(ys, ps, g) for g in GAINS]}
    out["s_per_item"] = sum(s for _, _, s in scores.values()) / len(scores) if scores else 0.0
    return out


def _num(x, fmt=".3f") -> str:
    return "-" if x is None else format(x, fmt)


def report(items: list[dict], arms: dict[str, dict], resamples: int = RESAMPLES) -> str:
    sums = {arm: summarize(items, s, resamples) for arm, s in arms.items()}
    lines = ["| arm | population | n (relevant) | AUC [95% bootstrap] | Brier | ECE | Brier, ECE after T "
             "| gain 10/25/50% | s/item |", "|---|---|---|---|---|---|---|---|---|"]
    for arm, s in sums.items():
        for pop in ("all", "held out", "residue"):
            if pop not in s:
                continue
            m = s[pop]
            lo, hi = m["auc_ci"]
            lines.append(f"| {arm} | {pop} | {m['n']} ({m['pos']}) | {_num(m['auc'])} [{_num(lo)}, {_num(hi)}] "
                         f"| {m['brier']:.3f} | {m['ece']:.3f} | {m['brier_t']:.3f}, {m['ece_t']:.3f} "
                         f"| {'/'.join(f'{g:.2f}' for g in m['gain'])} | {s['s_per_item']:.4f} |")
    if "embed" in arms:
        lines.append("")
        for arm in (a for a in arms if a != "embed"):
            for pop, keep in (("all", lambda r: True), ("residue", lambda r: r["residue"])):
                rows = [r for r in items if keep(r) and r["id"] in arms[arm] and r["id"] in arms["embed"]]
                d = paired_auc([r["y"] for r in rows], [arms[arm][r["id"]][1] for r in rows],
                               [arms["embed"][r["id"]][1] for r in rows], resamples)
                verdict = {"a better": f"{arm} better", "b better": "embed better", "tie": "tie"}[d["verdict"]]
                lines.append(f"paired bootstrap AUC({arm}) - AUC(embed), {pop} n={len(rows)}: {d['diff']:+.3f} "
                             f"[{d['ci'][0]:+.3f}, {d['ci'][1]:+.3f}] -> {verdict}")
    return "\n".join(lines)


# ---- fitters, inside Laya's venv

def _embed_fitter(model_dir: str, device: str):
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_dir)
    enc = AutoModel.from_pretrained(model_dir).to(device).eval()
    cache: dict[int, object] = {}

    def vectors(rows):
        todo = [r for r in rows if r["id"] not in cache]
        for start in range(0, len(todo), 64):
            chunk = todo[start:start + 64]
            batch = tok([r["text"][:MAX_CHARS] for r in chunk], padding=True, truncation=True,
                        max_length=512, return_tensors="pt").to(device)
            with torch.no_grad():
                cls = enc(**batch).last_hidden_state[:, 0]
            cls = torch.nn.functional.normalize(cls, dim=-1).cpu().numpy()
            for r, v in zip(chunk, cls):
                cache[r["id"]] = v
        return np.stack([cache[r["id"]] for r in rows])

    def fit(train, test):
        x, y = vectors(train), np.array([1.0 if r["y"] else 0.0 for r in train])
        mean, scale = x.mean(0), x.std(0)
        scale[scale == 0] = 1.0
        z = (x - mean) / scale
        w, b, n = np.zeros(z.shape[1]), 0.0, len(z)
        for _ in range(HEAD_ITERATIONS):
            err = 1 / (1 + np.exp(-(z @ w + b))) - y
            w = w - HEAD_LEARNING_RATE * (z.T @ err / n + HEAD_L2 / n * w)
            b -= HEAD_LEARNING_RATE * err.sum() / n
        zt = (vectors(test) - mean) / scale
        return (1 / (1 + np.exp(-(zt @ w + b)))).tolist()
    return fit


def _laya_scores(agent, rows) -> list[float]:
    got = agent.predict_batch([r["text"] for r in rows], QUESTION, batch_size=16)
    return [float(g["answers"]["relevant"]["noul"]) for g in got]


def _laya_zs_fitter(model_dir: str, device: str):
    import laya
    agent = laya.load(model_dir, device=device)
    return lambda train, test: _laya_scores(agent, test)


def _laya_ft_fitter(model_dir: str, device: str, epochs: int, micro_batch: int, grad_accum: int, seed: int):
    import laya
    from laya import train as T

    def fit(train, test):
        work = Path(tempfile.mkdtemp(prefix="laya-ft-"))
        try:
            data = work / "train.jsonl"
            data.write_text("".join(json.dumps({"state": r["text"], "questions": QUESTION,
                                                "expected": {"relevant": r["y"]}}) + "\n" for r in train),
                            encoding="utf-8")
            config = T.TrainConfig(epochs=epochs, micro_batch=micro_batch, grad_accum=grad_accum, seed=seed)
            T.finetune(str(data), model_dir, str(work / "ckpt"), config, device=device)
            return _laya_scores(laya.load(str(work / "ckpt"), device=device), test)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return fit


def _fit_main(args) -> int:
    items = load_labels(Path(args.labels))
    assigned = {int(k): v for k, v in json.loads(Path(args.folds).read_text(encoding="utf-8")).items()}
    if args.arm == "embed":
        fitter = _embed_fitter(args.embed_model, args.device)
    elif args.arm == "laya-zs":
        fitter = _laya_zs_fitter(args.model, args.device)
    else:
        fitter = _laya_ft_fitter(args.model, args.device, args.epochs, args.micro_batch, args.grad_accum, args.seed)
    fit_arm(items, assigned, fitter, Path(args.dest), k=args.k)
    return 0


def _fit_command(args, arm: str, folds_path: Path, dest: Path) -> list[str]:
    return [args.python, "-I", str(Path(__file__).resolve()), "fit", "--arm", arm, "--labels", str(args.labels),
            "--folds", str(folds_path), "--out", str(dest), "--model", args.model, "--embed-model", args.embed_model,
            "--device", args.device, "--epochs", str(args.epochs), "--micro-batch", str(args.micro_batch),
            "--grad-accum", str(args.grad_accum), "--seed", str(args.seed), "--k", str(args.k)]


def run(labels: Path, out: Path, arms, fit, k: int = FOLDS, resamples: int = RESAMPLES) -> str:
    """Write the folds once, score each arm on them (fit(arm, folds_path, dest)), then compare."""
    items = load_labels(labels)
    out.mkdir(parents=True, exist_ok=True)
    folds_path = out / "folds.json"
    folds_path.write_text(json.dumps(folds(items, k)), encoding="utf-8")
    scored = {}
    for arm in arms:
        dest = out / f"{arm}.scores.jsonl"
        fit(arm, folds_path, dest)
        scored[arm] = read_scores(dest)
    digest = hashlib.sha256(Path(labels).read_bytes()).hexdigest()[:16]
    head = (f"labels {labels} sha256 {digest}: {len(items)} ({sum(r['y'] for r in items)} relevant), "
            f"{sum(r['held_out'] for r in items)} held out, {sum(r['residue'] for r in items)} residue "
            f"(cascade stage not lexicon); {k} folds, seed {FOLD_SEED}")
    text = head + "\n\n" + report(items, scored, resamples)
    (out / "report.txt").write_text(text + "\n", encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.analysis.laya_finetune", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fit", "run"):
        p = sub.add_parser(name)
        p.add_argument("--labels", default=str(LABELS))
        p.add_argument("--model", required=True, help="local Laya checkpoint directory")
        p.add_argument("--embed-model", required=True, help="local bge-small-en-v1.5 snapshot directory")
        p.add_argument("--device", default="mps")
        p.add_argument("--epochs", type=int, default=4)
        p.add_argument("--micro-batch", type=int, default=8)
        p.add_argument("--grad-accum", type=int, default=1)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--k", type=int, default=FOLDS)
    sub.choices["fit"].add_argument("--arm", choices=ARMS, required=True)
    sub.choices["fit"].add_argument("--folds", required=True)
    sub.choices["fit"].add_argument("--out", dest="dest", required=True)
    r = sub.choices["run"]
    r.add_argument("--python", required=True, help="Laya venv's python")
    r.add_argument("--out", required=True)
    r.add_argument("--arms", default=",".join(ARMS))
    r.add_argument("--resamples", type=int, default=RESAMPLES)
    args = ap.parse_args(argv)
    if args.cmd == "fit":
        return _fit_main(args)
    print(run(Path(args.labels), Path(args.out), args.arms.split(","),
              lambda arm, f, d: subprocess.run(_fit_command(args, arm, f, d), check=True),
              k=args.k, resamples=args.resamples), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
