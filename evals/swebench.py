"""SWE-bench Verified calibration of the repo lane's generation and apply path against SWE-Llama 13B. #922."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import random
import re
import shlex
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from evals import repo
from evals.claims_report import wilson
from harness.paired import sign_test

REFERENCE_RUN = "20231010_rag_swellama13b"
RESULTS_URL = ("https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/verified/"
               f"{REFERENCE_RUN}/results/results.json")
PREDS_URL = f"https://swe-bench-submissions.s3.amazonaws.com/verified/{REFERENCE_RUN}/all_preds.jsonl"
#: (hub dataset, revision, parquet file): the sample's frame and the prompts sent verbatim.
VERIFIED = ("princeton-nlp/SWE-bench_Verified", "c104f840cc67f8b6eec6f759ebc8b2693d585d4a",
            "data/test-00000-of-00001.parquet")
PROMPTS = ("princeton-nlp/SWE-bench_bm25_13K", "eb1d4af35aa2ffd942a72b598f0e4ddf9cb90105",
           "data/test-00000-of-00001.parquet")
HARNESS_PIN = "swebench==5.0.2"
HARNESS_DATASET = "SWE-bench/SWE-bench_Verified"
#: The reference's ids with no comparable outcome: never generated, or the harness itself failed.
EXCLUDED = ("no_generation", "reset_failed", "install_fail")
DEFAULT_N = 100
DEFAULT_SEED = 922
DEFAULT_MAX_TOKENS = 4096
FETCH_TIMEOUT_S = 120.0
PROPS_TIMEOUT_S = 30.0
COMPLETION_TIMEOUT_S = 3600.0
MARGIN = 0.10
ALPHA = 0.05
# The harness skips an empty model_patch without running tests, so the negative control must apply.
NULL_PATCH = ("diff --git a/.sohot-null-control b/.sohot-null-control\nnew file mode 100644\n"
              "--- /dev/null\n+++ b/.sohot-null-control\n@@ -0,0 +1 @@\n+null control\n")
#: Greedy, as run_llama.py at SWE-bench d39fcaa81f, every other sampler off; the server's echo is recorded too.
GREEDY = {"temperature": 0.0, "top_k": 1, "top_p": 1.0, "min_p": 0.0, "typical_p": 1.0, "repeat_penalty": 1.0,
          "presence_penalty": 0.0, "frequency_penalty": 0.0, "dry_multiplier": 0.0, "xtc_probability": 0.0,
          "seed": 0}
STOPPING = "eos or n_predict; upstream RepeatingTokensCriteria(100, 10) not applied"
APPLY_PATCH_FAIL = ">>>>> Patch Apply Failed"
KINDS = ("gold", "null", "model", "upstream", "reference")
_QUANT = re.compile(r"(?i)\b(IQ\d_\w+|Q\d(?:_[A-Z0-9]+)*|F16|BF16|F32)\b")
_TAG = re.compile(r"\<([\w-]+)\>(.*?)\<\/\1\>", re.S)
_UP_FENCE = re.compile(r"```(\w+)?\n(.*?)```", re.S)


def harness_extract_diff(response: str | None) -> str | None:
    """swebench.inference.make_datasets.utils.extract_diff, verbatim in behaviour (MIT)."""
    if response is None:
        return None
    diffs, others = [], []
    for pattern in (_TAG, _UP_FENCE):
        for code, match in pattern.findall(response):
            (diffs if code in {"diff", "patch"} else others).append(match)
    if diffs:
        return diffs[0]
    if others:
        return others[0]
    return response.split("</s>")[0]


def prediction(instance_id: str, model: str, patch: str) -> dict:
    return {"instance_id": instance_id, "model_name_or_path": model, "model_patch": patch}


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _fetch(url: str) -> bytes:
    import httpx
    got = httpx.get(url, timeout=FETCH_TIMEOUT_S, follow_redirects=True)
    got.raise_for_status()
    return got.content


def _hub_rows(spec: tuple, columns: list[str]) -> list[dict]:
    """A pinned hub parquet's columns as rows; needs pyarrow (`uv run --with pyarrow`)."""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit("reading the hub parquet needs pyarrow: "
                         "uv run --with pyarrow python -m evals.swebench ...") from exc
    from huggingface_hub import hf_hub_download
    name, revision, filename = spec
    local = hf_hub_download(name, filename, repo_type="dataset", revision=revision)
    return pq.read_table(local, columns=columns).to_pylist()


def _rows(path: str | None, spec: tuple, columns: list[str]) -> list[dict]:
    if not path:
        return _hub_rows(spec, columns)
    if path.endswith(".parquet"):
        import pyarrow.parquet as pq
        return pq.read_table(path, columns=columns).to_pylist()
    return read_jsonl(Path(path))


def eligible(results: dict) -> tuple[set, dict]:
    """The reference's generated ids less its excluded ones, and why each excluded id went."""
    out = set(results.get("generated", []))
    why = {}
    for key in EXCLUDED:
        for iid in results.get(key, []):
            why.setdefault(iid, key)
            out.discard(iid)
    return out, why


def allocate(sizes: dict, n: int) -> dict:
    """Proportional allocation over strata by largest remainder; ties go to the larger stratum, then the key."""
    total = sum(sizes.values())
    if n >= total:
        return dict(sizes)
    quota = {k: n * v / total for k, v in sizes.items()}
    got = {k: int(q) for k, q in quota.items()}
    order = sorted(sizes, key=lambda k: (-(quota[k] - got[k]), -sizes[k], k))
    for k in order[: n - sum(got.values())]:
        got[k] += 1
    return got


def draw(rows: list[dict], results: dict, n: int, seed: int) -> dict:
    """A seeded sample of Verified ids stratified by (repo, difficulty), within the reference's comparable ids."""
    keep, why = eligible(results)
    strata = defaultdict(list)
    dropped = dict(why)
    for row in rows:
        iid = row["instance_id"]
        if iid in keep:
            strata[(row["repo"], row.get("difficulty") or "unknown")].append(iid)
        elif iid not in dropped:
            dropped[iid] = "not_in_reference"
    alloc = allocate({k: len(v) for k, v in strata.items()}, n)
    rng = random.Random(seed)
    ids = []
    for key in sorted(strata):
        ids += rng.sample(sorted(strata[key]), alloc[key])
    return {"seed": seed, "n": len(ids), "ids": sorted(ids),
            "strata": [{"repo": k[0], "difficulty": k[1], "eligible": len(strata[k]), "drawn": alloc[k]}
                       for k in sorted(strata)],
            "excluded": dict(Counter(dropped.values()))}


def cmd_sample(a) -> int:
    run = Path(a.run_dir)
    raw = Path(a.results).read_bytes() if a.results else _fetch(RESULTS_URL)
    results = json.loads(raw)
    rows = _rows(a.verified, VERIFIED, ["instance_id", "repo", "difficulty"])
    got = draw(rows, results, a.n, a.seed)
    got["sources"] = {"verified": {"dataset": VERIFIED[0], "revision": VERIFIED[1], "path": a.verified or ""},
                      "reference": {"run": REFERENCE_RUN, "url": a.results or RESULTS_URL,
                                    "sha256": hashlib.sha256(raw).hexdigest()}}
    (run / "reference").mkdir(parents=True, exist_ok=True)
    (run / "reference" / "results.json").write_bytes(raw)
    if a.reference_preds or not a.no_reference_preds:
        try:
            preds = Path(a.reference_preds).read_bytes() if a.reference_preds else _fetch(PREDS_URL)
            (run / "reference" / "all_preds.jsonl").write_bytes(preds)
            got["sources"]["reference"]["preds"] = {"url": a.reference_preds or PREDS_URL,
                                                    "sha256": hashlib.sha256(preds).hexdigest()}
        except Exception as exc:  # the published predictions are a bonus control, not a precondition
            print(f"sample: reference predictions not fetched: {exc}", file=sys.stderr)
    write_json(run / "sample.json", got)
    print(f"sample: {got['n']} ids over {len(got['strata'])} strata, seed {got['seed']}; "
          f"excluded {got['excluded']}; wrote {run / 'sample.json'}")
    return 0


def prompt_text(text: str) -> str:
    """run_llama.py makes SWE-Llama's input end in exactly two newline tokens; the same at the character level."""
    return text if text.endswith("\n\n") else text + "\n"


def server_props(server: str, get=None) -> dict:
    """llama-server's /props: build, model path, context; {} when it does not answer."""
    import httpx
    try:
        got = get(server.rstrip("/") + "/props") if get else httpx.get(server.rstrip("/") + "/props", timeout=PROPS_TIMEOUT_S).json()
    except Exception:
        return {}
    settings = got.get("default_generation_settings") or {}
    return {"build_info": got.get("build_info", ""), "model_path": got.get("model_path", ""),
            "n_ctx": settings.get("n_ctx") or got.get("n_ctx")}


def quant_of(model_path: str) -> str:
    m = _QUANT.search(Path(model_path or "").name)
    return m.group(1).upper() if m else ""


def complete(server: str, prompt: str, max_tokens: int, post=None) -> dict:
    """One raw /completion: SWE-Llama has no chat template, so the prompt goes as text."""
    payload = {"prompt": prompt, "n_predict": max_tokens, "stream": False, "cache_prompt": False, **GREEDY}
    if post:
        return post(server.rstrip("/") + "/completion", payload)
    import httpx
    got = httpx.post(server.rstrip("/") + "/completion", json=payload, timeout=COMPLETION_TIMEOUT_S)
    got.raise_for_status()
    return got.json()


def build_predictions(run: Path, ids: list[str], model: str) -> tuple[list[dict], list[dict]]:
    """Ours (repo.extract_diff) and the harness's (harness_extract_diff) from the same stored replies."""
    ours, upstream = [], []
    for iid in ids:
        path = run / "replies" / f"{iid}.json"
        if not path.is_file():
            continue
        reply = read_json(path)["content"]
        ours.append(prediction(iid, model, repo.extract_diff(reply)))
        upstream.append(prediction(iid, model, harness_extract_diff(reply) or ""))
    return ours, upstream


def cmd_predict(a, post=None, get=None) -> int:
    run = Path(a.run_dir)
    ids = read_json(run / "sample.json")["ids"][: a.limit or None]
    rows = _rows(a.prompts, PROMPTS, ["instance_id", "text"])
    texts = {r["instance_id"]: r["text"] for r in rows if r["instance_id"] in set(ids)}
    missing = sorted(set(ids) - set(texts))
    props = server_props(a.server, get=get)
    receipt = {"reference_run": REFERENCE_RUN, "model": a.model, "weights": a.weights,
               "quant": a.quant or quant_of(props.get("model_path", "")), "server": props,
               "sampling": GREEDY, "n_predict": a.max_tokens, "stopping": STOPPING,
               "prompt": "text field verbatim, newline-padded to end in two",
               "prompts": {"dataset": PROMPTS[0], "revision": PROMPTS[1], "path": a.prompts or ""},
               "harness": HARNESS_PIN, "extract_diff": "evals.repo.extract_diff",
               "machine": {"system": platform.system(), "machine": platform.machine()},
               "started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "missing_prompts": missing}
    write_json(run / "receipt.json", receipt)
    for iid in ids:
        out = run / "replies" / f"{iid}.json"
        if out.is_file() or iid not in texts:
            continue
        started = time.perf_counter()
        got = complete(a.server, prompt_text(texts[iid]), a.max_tokens, post=post)
        write_json(out, {"instance_id": iid, "content": got.get("content", ""),
                         "stop_type": got.get("stop_type", ""), "stopped_eos": got.get("stopped_eos"),
                         "stopped_limit": got.get("stopped_limit"), "truncated": got.get("truncated"),
                         "tokens_evaluated": got.get("tokens_evaluated"),
                         "tokens_predicted": got.get("tokens_predicted"),
                         "generation_settings": got.get("generation_settings", {}),
                         "timings": got.get("timings", {}), "wall_s": round(time.perf_counter() - started, 3)})
        print(f"predict: {iid} {got.get('tokens_predicted')} tokens", flush=True)
    stored = [run / "replies" / f"{i}.json" for i in ids if (run / "replies" / f"{i}.json").is_file()]
    receipt["served_sampling"] = read_json(stored[0]).get("generation_settings", {}) if stored else {}
    ours, upstream = build_predictions(run, ids, a.model)
    write_jsonl(run / "predictions.jsonl", ours)
    write_jsonl(run / "predictions.upstream.jsonl", upstream)
    receipt["finished"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    receipt["replies"] = len(ours)
    write_json(run / "receipt.json", receipt)
    print(f"predict: {len(ours)} of {len(ids)} predictions in {run / 'predictions.jsonl'}"
          + (f"; {len(missing)} ids have no prompt" if missing else ""))
    return 0


def _patches(path: Path) -> dict:
    return {r["instance_id"]: r.get("model_patch") or "" for r in read_jsonl(path)} if path.is_file() else {}


def grade_script(ids: list[str], runs: list[tuple[str, str, list[str]]], workers: int) -> str:
    lines = ["#!/bin/sh",
             "# Grade this run directory with the official SWE-bench harness on an x86_64 Docker host (#922).",
             "set -eu", 'cd "$(dirname "$0")/.."',
             'if [ "$(uname -m)" != x86_64 ] && [ -z "${SOHOT_GRADE_ANY_ARCH:-}" ]; then',
             '  echo "grade.sh: the harness images are x86_64; this host is $(uname -m)" >&2; exit 2', "fi",
             "docker info >/dev/null",
             "[ -x .swebench-venv/bin/python ] || python3 -m venv .swebench-venv",
             f".swebench-venv/bin/pip install -q {shlex.quote(HARNESS_PIN)}",
             "mkdir -p grades/reports",
             ".swebench-venv/bin/pip freeze | grep -i '^swebench' > grades/harness.txt",
             "docker version --format '{{.Server.Os}}/{{.Server.Arch}} {{.Server.Version}}' >> grades/harness.txt",
             "run() {",
             "  kind=$1; preds=$2; shift 2",
             "  rm -rf \"logs/run_evaluation/sohot922-$kind\" \"grades/$kind\"",
             f"  .swebench-venv/bin/python -m swebench.harness.run_evaluation -d {HARNESS_DATASET} -s test \\",
             f"    -p \"$preds\" --run_id \"sohot922-$kind\" --max_workers {int(workers)} --report_dir grades/reports -i \"$@\"",
             "  mv \"logs/run_evaluation/sohot922-$kind\" \"grades/$kind\"",
             "}"]
    for kind, preds, which in runs:
        if which:
            lines.append(f"run {kind} {shlex.quote(preds)} {' '.join(shlex.quote(i) for i in which)}")
    lines.append('echo "grade.sh: done; copy grades/ back and run python -m evals.swebench compare"')
    return "\n".join(lines) + "\n"


def cmd_grade(a) -> int:
    """Write the hand-off: the controls' predictions and grade.sh, which runs the official harness elsewhere."""
    run = Path(a.run_dir)
    ids = read_json(run / "sample.json")["ids"]
    write_jsonl(run / "grade" / "null.jsonl", [prediction(i, "sohot-null", NULL_PATCH) for i in ids])
    runs = [("gold", "gold", ids), ("null", "grade/null.jsonl", ids)]
    ours = _patches(run / "predictions.jsonl")
    if ours:
        runs.append(("model", "predictions.jsonl", sorted(i for i, p in ours.items() if p.strip())))
        upstream = _patches(run / "predictions.upstream.jsonl")
        differ = sorted(i for i, p in upstream.items() if p.strip() and p.strip() != ours.get(i, "").strip())
        runs.append(("upstream", "predictions.upstream.jsonl", differ))
    reference = _patches(run / "reference" / "all_preds.jsonl")
    if reference:
        rows = [prediction(i, REFERENCE_RUN, reference[i]) for i in ids if reference.get(i, "").strip()]
        write_jsonl(run / "grade" / "reference.jsonl", rows)
        runs.append(("reference", "grade/reference.jsonl", [r["instance_id"] for r in rows]))
    script = run / "grade" / "grade.sh"
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write(grade_script(ids, runs, a.workers))
    script.chmod(0o755)
    print(f"grade: wrote {script} for {', '.join(f'{k} ({len(w)})' for k, _, w in runs)}.\n"
          f"Copy {run} to an x86_64 host with Docker and Python 3.10+, run `sh grade/grade.sh` there,\n"
          f"copy its grades/ back into {run}, then: python -m evals.swebench compare {run}")
    return 0


def graded(run: Path, kind: str) -> dict | None:
    """Per id from a harness log tree: {"applied", "resolved"}, or None for a harness error; None if ungraded."""
    root = run / "grades" / kind
    if not root.is_dir():
        return None
    out = {}
    for inst in sorted(p for p in root.glob("*/*") if p.is_dir()):
        iid = inst.name
        report = inst / "report.json"
        if report.is_file():
            got = read_json(report).get(iid, {})
            out[iid] = {"applied": bool(got.get("patch_successfully_applied")),
                        "resolved": bool(got.get("resolved"))}
            continue
        log = inst / "run_instance.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        out[iid] = {"applied": False, "resolved": False} if APPLY_PATCH_FAIL in text else None
    return out


def controls(ids: list[str], gold: dict | None, null: dict | None) -> tuple[list[str], dict]:
    """The ids whose gold patch resolves and whose null patch does not, and why each other id was dropped."""
    kept, dropped = [], {}
    for iid in ids:
        g = (gold or {}).get(iid)
        z = (null or {}).get(iid)
        if gold is None or null is None:
            dropped[iid] = "controls ungraded"
        elif g is None or not g["resolved"]:
            dropped[iid] = "gold did not resolve"
        elif z is None:
            dropped[iid] = "null control errored"
        elif z["resolved"]:
            dropped[iid] = "null patch resolved"
        else:
            kept.append(iid)
    return kept, dropped


def paired(ids: list[str], ours: dict, theirs: dict, field: str) -> dict:
    """2x2 on one per-instance outcome, the exact McNemar on its discordant cells, and each rate's interval."""
    both = sum(1 for i in ids if ours[i][field] and theirs[i][field])
    only_ours = sum(1 for i in ids if ours[i][field] and not theirs[i][field])
    only_theirs = sum(1 for i in ids if theirs[i][field] and not ours[i][field])
    n = len(ids)
    k_ours, k_theirs = both + only_ours, both + only_theirs
    p = sign_test(only_ours, only_ours + only_theirs)
    diff = (k_ours - k_theirs) / n if n else 0.0
    return {"n": n, "ours": k_ours, "theirs": k_theirs, "ours_ci": wilson(k_ours, n),
            "theirs_ci": wilson(k_theirs, n), "both": both, "only_ours": only_ours,
            "only_theirs": only_theirs, "neither": n - both - only_ours - only_theirs,
            "agreement": round((n - only_ours - only_theirs) / n, 4) if n else 0.0,
            "diff": round(diff, 4), "mcnemar_p": round(p, 4),
            "agrees": bool(n) and abs(diff) <= MARGIN and p > ALPHA}


def published(results: dict, ids: list[str]) -> dict:
    applied, resolved = set(results.get("applied", [])), set(results.get("resolved", []))
    return {i: {"applied": i in applied or i in resolved, "resolved": i in resolved} for i in ids}


def _files(patch: str) -> frozenset:
    return frozenset(re.findall(r"^diff --git a/(\S+) b/", repo.with_git_headers(patch or ""), re.M))


def extraction(run: Path, ids: list[str]) -> dict:
    """What can be said before any grading: patch presence, extractor disagreement, sameness to the reference."""
    ours = _patches(run / "predictions.jsonl")
    upstream = _patches(run / "predictions.upstream.jsonl")
    ref = _patches(run / "reference" / "all_preds.jsonl")
    have = [i for i in ids if i in ours]
    out = {"replies": len(have), "with_patch": sum(1 for i in have if ours[i].strip()),
           "extractors_differ": sum(1 for i in have if ours[i].strip() != (upstream.get(i) or "").strip())}
    if ref:
        both = [i for i in have if i in ref]
        out["reference_patches"] = len(both)
        out["identical_to_reference"] = sum(1 for i in both if ours[i].strip() == ref[i].strip())
        out["same_files_as_reference"] = sum(1 for i in both if _files(ours[i]) and _files(ours[i]) == _files(ref[i]))
    return out


def compare(run: Path) -> dict:
    sample = read_json(run / "sample.json")
    ids = sample["ids"]
    results = read_json(run / "reference" / "results.json")
    grades = {k: graded(run, k) for k in KINDS}
    harness = run / "grades" / "harness.txt"
    out = {"run_dir": str(run), "reference_run": REFERENCE_RUN, "sampled": len(ids),
           "harness": harness.read_text(encoding="utf-8").strip() if harness.is_file() else "",
           "extraction": extraction(run, ids), "graded": {k: v is not None for k, v in grades.items()}}
    kept, dropped = controls(ids, grades["gold"], grades["null"])
    out["dropped"] = dropped
    ours_patch = _patches(run / "predictions.jsonl")
    model = grades["model"]
    if model is None or not kept:
        out["status"] = "pending"
        return out
    ours = {}
    for iid in kept:
        if iid in ours_patch and not ours_patch[iid].strip():
            ours[iid] = {"applied": False, "resolved": False}
        elif model.get(iid) is not None:
            ours[iid] = model[iid]
        else:
            dropped[iid] = "model patch ungraded or harness error"
    kept = [i for i in kept if i in ours]
    out["retained"] = len(kept)
    ref = published(results, kept)
    out["vs_published"] = {f: paired(kept, ours, ref, f) for f in ("applied", "resolved")}
    regraded = grades["reference"]
    if regraded is not None:
        common = [i for i in kept if regraded.get(i) is not None]
        mine = {i: regraded[i] for i in common}
        out["vs_regraded"] = {f: paired(common, ours, mine, f) for f in ("applied", "resolved")}
        out["harness_drift"] = {f: paired(common, mine, ref, f) for f in ("applied", "resolved")}
    out["status"] = "graded"
    return out


def _rate(k: int, n: int, ci) -> str:
    return f"{k}/{n} {k / n:.1%} [{ci[0]:.1%}, {ci[1]:.1%}]" if n else "0/0"


def render(got: dict) -> str:
    lines = [f"SWE-bench Verified calibration against {got['reference_run']}: {got['run_dir']}",
             f"sampled {got['sampled']}; harness {got['harness'] or 'unrecorded'}"]
    ex = got["extraction"]
    lines.append("extraction: " + ", ".join(f"{k} {v}" for k, v in ex.items()))
    lines.append("graded: " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in got["graded"].items()))
    if got["status"] == "pending":
        lines.append("grading pending: python -m evals.swebench grade RUN_DIR writes grade/grade.sh "
                     "for an x86_64 Docker host; copy its grades/ back here")
        return "\n".join(lines)
    lines.append(f"retained {got['retained']} after controls; dropped {len(got['dropped'])}")
    for iid, why in sorted(got["dropped"].items()):
        lines.append(f"  dropped {iid}: {why}")
    for title, key, a, b in (("ours vs published reference", "vs_published", "ours", "published"),
                             ("ours vs reference regraded here", "vs_regraded", "ours", "regraded"),
                             ("regraded vs published (harness drift)", "harness_drift", "regraded", "published")):
        if key not in got:
            continue
        lines.append(title)
        for field, t in got[key].items():
            verdict = "within margin" if t["agrees"] else "gap"
            lines.append(f"  {field:8} {a} {_rate(t['ours'], t['n'], t['ours_ci'])}  "
                         f"{b} {_rate(t['theirs'], t['n'], t['theirs_ci'])}  diff {t['diff']:+.1%}  "
                         f"agree {t['agreement']:.1%}  discordant {t['only_ours']}/{t['only_theirs']}  "
                         f"McNemar p={t['mcnemar_p']:.4f}  {verdict}")
    return "\n".join(lines)


def cmd_compare(a) -> int:
    got = compare(Path(a.run_dir))
    print(json.dumps(got, indent=2, sort_keys=True) if a.json else render(got))
    return 0 if got["status"] == "graded" else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.swebench", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="seeded stratified Verified ids comparable with the reference")
    s.add_argument("run_dir")
    s.add_argument("--n", type=int, default=DEFAULT_N)
    s.add_argument("--seed", type=int, default=DEFAULT_SEED)
    s.add_argument("--verified", help="Verified rows (jsonl or parquet); default the pinned hub revision")
    s.add_argument("--results", help="the reference results.json; default SWE-bench/experiments")
    s.add_argument("--reference-preds", help="the reference all_preds.jsonl; default its S3 copy")
    s.add_argument("--no-reference-preds", action="store_true")
    p = sub.add_parser("predict", help="ask llama-server for each sampled id; write predictions.jsonl")
    p.add_argument("run_dir")
    p.add_argument("--server", required=True, help="llama-server base URL serving SWE-Llama")
    p.add_argument("--model", default="sohot-swellama13b", help="model_name_or_path in predictions.jsonl")
    p.add_argument("--weights", default="princeton-nlp/SWE-Llama-13b")
    p.add_argument("--quant", default="", help="default: read from the served model's file name")
    p.add_argument("--prompts", help="bm25_13K rows (jsonl or parquet); default the pinned hub revision")
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument("--limit", type=int, default=0)
    g = sub.add_parser("grade", help="write the hand-off to the official harness on an x86_64 Docker host")
    g.add_argument("run_dir")
    g.add_argument("--workers", type=int, default=4)
    c = sub.add_parser("compare", help="per-instance applied and resolved against the reference")
    c.add_argument("run_dir")
    c.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    return {"sample": cmd_sample, "predict": cmd_predict, "grade": cmd_grade, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
