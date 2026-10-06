"""The decide lane's decider engine: one context and schema through strands-decider.

Run by the decider venv (scripts/decider-score.sh), never imported by this
repo's environment. Imports nothing from `harness` beyond itself. #467.

An enum field is a `choice` question over its choices; a boolean field is a
`noul` question whose P(true) is the field's distribution.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", required=True, help="HF repo id of a strands-decider checkpoint")
    p.add_argument("--revision", default=None)
    p.add_argument("--context", required=True)
    p.add_argument("--schema", required=True, help="the flat schema as JSON")
    p.add_argument("--out", required=True)
    p.add_argument("--device", default=None, help="mlx, cuda, mps or cpu")
    return p.parse_args(argv)


def _key(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def questions(schema: dict) -> dict:
    """Each field as a System One question, in the API's wire shape."""
    out = {}
    for name, spec in schema.items():
        notes = spec.get("choice_descriptions") or {}
        notes = {_key(k): v for k, v in notes.items()} if isinstance(notes, dict) else {}
        text = str(spec.get("description") or name).strip()
        if spec.get("type") == "boolean":
            q = {"type": "noul", "instructions": text}
            crit = {k: notes[k] for k in ("true", "false") if notes.get(k)}
            if crit:
                q["criteria"] = crit
        elif spec.get("type") == "enum":
            q = {"type": "choice", "instructions": text,
                 "criteria": {_key(c): notes.get(_key(c)) for c in spec.get("choices") or []}}
        else:
            raise SystemExit(f"field {name!r}: type {spec.get('type')!r} has no decider question")
        out[name] = q
    return out


def artifact(answers: dict, schema: dict) -> tuple[dict, dict]:
    """The decide lane's answers and per-choice probabilities from System One answers."""
    got, probs = {}, {}
    for name, spec in schema.items():
        a = answers.get(name) or {}
        if spec.get("type") == "boolean" and a.get("type") == "noul":
            p = float(a["noul"])
            probs[name] = {"false": 1.0 - p, "true": p}
            got[name] = "true" if p >= 0.5 else "false"
        elif a.get("type") == "choice":
            probs[name] = {str(k): float(v) for k, v in (a.get("probabilities") or {}).items()}
            got[name] = str(a.get("choice"))
    return got, probs


def default_device() -> str:
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "mlx"
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def checkpoint(repo: str, revision: str | None) -> tuple[str, str]:
    """A local snapshot of `repo` and the revision it resolved to."""
    from huggingface_hub import snapshot_download
    path = Path(snapshot_download(repo, revision=revision))
    return str(path), path.name


def default_ask(path: str, device: str, context: str, qs: dict) -> dict:
    from strands_decider.infer import load_engine
    from strands_decider.schema import SystemOneRequest
    engine = load_engine(path, device=device)
    req = SystemOneRequest.model_validate({"state": context, "questions": qs})
    return engine.evaluate(req).model_dump()


def peak_gib() -> float:
    try:
        import mlx.core as mx
        return round(mx.get_peak_memory() / 2 ** 30, 3)
    except Exception:  # noqa: BLE001
        return 0.0


def run(args, ask=default_ask, resolve=checkpoint) -> dict:
    """Score one case and write the canonical artifact the decide checker reads."""
    schema = json.loads(args.schema)
    device = args.device or default_device()
    path, revision = resolve(args.model, args.revision)
    response = ask(path, device, args.context, questions(schema))
    answers, probs = artifact(response.get("answers") or {}, schema)
    body = {"answers": answers, "probabilities": probs, "model": args.model,
            "revision": revision, "device": device, "peak_gib": peak_gib()}
    Path(args.out).write_text(json.dumps(body, indent=2, allow_nan=False) + "\n",
                              encoding="utf-8")
    return body


def main(argv=None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
