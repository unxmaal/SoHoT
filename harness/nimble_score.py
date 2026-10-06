"""The decide lane's nimble engine: one context and schema through nimble's own scorer.

Run by the nimble venv (scripts/nimble-score.sh), never imported by this repo's
environment. Imports nothing from `harness` beyond itself. #423.

A peft adapter is merged onto the base its schema_config.json pins, once, into
<models>/<repo tail>-<revision>; nimble's MLX scorer cannot load an adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", required=True, help="HF repo id: a nimble adapter or full checkpoint")
    p.add_argument("--revision", default=None)
    p.add_argument("--context", required=True)
    p.add_argument("--schema", required=True, help="the flat schema as JSON")
    p.add_argument("--out", required=True)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--models", default=os.environ.get("NIMBLE_MODELS", ""),
                   help="where merged checkpoints live")
    return p.parse_args(argv)


def merged_dir(models: str, repo: str, revision: str) -> Path:
    return Path(models) / f"{repo.rsplit('/', 1)[-1]}-{revision}"


def prepare(repo: str, revision: str | None, models: str) -> dict:
    """The scorer's settings for `repo`, merging an adapter onto its base first."""
    from huggingface_hub import snapshot_download

    snapshot = Path(snapshot_download(repo, revision=revision))
    contract_file = snapshot / "schema_config.json"
    contract = json.loads(contract_file.read_text(encoding="utf-8")) if contract_file.exists() else {}
    path = snapshot
    if (snapshot / "adapter_config.json").exists():
        if not contract.get("model"):
            raise SystemExit(f"{repo}: an adapter with no schema_config.json base to merge onto")
        path = merged_dir(models, repo, snapshot.name)
        if not (path / "READY.json").exists():
            merge(snapshot, contract, path, repo)
    return {"model_path": str(path), "model_id": repo, "revision": snapshot.name,
            "max_input_tokens": int(contract.get("max_length") or 2048)}


def merge(snapshot: Path, contract: dict, out: Path, repo: str) -> None:
    """The README's merge: base at its pinned revision, adapter merged, on the CPU."""
    import torch
    from peft import PeftModel
    from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

    print(f"merging {repo} onto {contract['model']}@{contract.get('revision')}",
          file=sys.stderr, flush=True)
    base = Qwen3_5ForConditionalGeneration.from_pretrained(
        contract["model"], revision=contract.get("revision"),
        dtype=torch.bfloat16, device_map="cpu")
    merged = PeftModel.from_pretrained(base, snapshot).merge_and_unload(safe_merge=True)
    out.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(out)
    (out / "schema_config.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    AutoTokenizer.from_pretrained(snapshot).save_pretrained(out)
    weights = snapshot / "adapter_model.safetensors"
    (out / "READY.json").write_text(json.dumps({
        "model": repo, "revision": snapshot.name,
        "adapter_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
    }, indent=2), encoding="utf-8")


def default_scorer(settings: dict, temperature):
    from nimble.scoring.parallel_scorer import ParallelScorer
    return ParallelScorer(temperature=temperature, **settings)


def peak_gib() -> float:
    try:
        import mlx.core as mx
        return round(mx.get_peak_memory() / 2 ** 30, 3)
    except Exception:  # noqa: BLE001
        return 0.0


def run(args, scorer_factory=default_scorer, settings: dict | None = None) -> dict:
    """Score one case and write the canonical artifact the decide checker reads."""
    schema = json.loads(args.schema)
    settings = settings or prepare(args.model, args.revision, args.models)
    scorer = scorer_factory(settings, args.temperature)
    result = scorer.score(args.context, schema)
    fields = result.get("fields") or {}
    body = {
        "answers": dict(result.get("output") or {}),
        "probabilities": {n: dict(f.get("scores") or {}) for n, f in fields.items()},
        "model": result.get("model") or settings.get("model_id"),
        "revision": result.get("revision") or settings.get("revision"),
        "temperature": result.get("temperature"),
        "temperature_fitted": result.get("temperature_fitted"),
        "peak_gib": peak_gib(),
    }
    Path(args.out).write_text(json.dumps(body, indent=2, allow_nan=False) + "\n",
                              encoding="utf-8")
    return body


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.models:
        raise SystemExit("no --models directory for merged checkpoints; set NIMBLE_MODELS")
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
