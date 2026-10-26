"""Frames through mlx-vlm, in the mlx-vlm venv (#1282). Run by scripts/mlx-vlm.sh.

Imports nothing from this package at module level but hf_task's resume loop. A checkpoint
whose config names its own model file is refused, never executed.
"""
from __future__ import annotations

import argparse
import functools
import json
import sys

from harness import hf_task


def read_config(model: str, revision: str | None = None) -> dict:
    """config.json of a local folder or a hub repo, read before anything is built from it."""
    from pathlib import Path
    local = Path(model) / "config.json"
    if local.is_file():
        return json.loads(local.read_text(encoding="utf-8"))
    from huggingface_hub import hf_hub_download
    return json.loads(Path(hf_hub_download(model, "config.json", revision=revision)).read_text(encoding="utf-8"))


def load(model: str, revision: str | None = None, device: str = "gpu"):
    """Load once; returns ask(image, prompt, max_tokens) -> (reply, cut at the budget)."""
    import contextlib

    import mlx.core as mx
    if device == "cpu":
        mx.set_default_device(mx.cpu)
    from mlx_vlm import apply_chat_template, generate
    from mlx_vlm import load as mlx_load
    if device == "cpu":
        from mlx_vlm.generate import dispatch
        # mlx-vlm 0.7.10 sizes a Metal wired limit from a key the CPU device does not report.
        dispatch.wired_limit = lambda model, streams=None: contextlib.nullcontext()
    net, proc = mlx_load(model, revision=revision)
    cache: dict[str, str] = {}

    def ask(image: str, prompt: str, max_tokens: int):
        if prompt not in cache:
            cache[prompt] = apply_chat_template(proc, net.config, prompt, num_images=1)
        got = generate(net, proc, cache[prompt], image=[image], max_tokens=max_tokens, temperature=0.0,
                       verbose=False)
        return str(getattr(got, "text", got)).strip(), getattr(got, "finish_reason", "") == "length"
    return ask


def label_images(model: str, images, prompt: str, *, ask, max_tokens: int):
    for image in images:
        yield ask(image, prompt, max_tokens)


def main(argv=None, load=load, config=read_config) -> int:
    from evals.vision import DEVICES, REPLY_MAX_TOKENS
    p = argparse.ArgumentParser(prog="mlx-vlm-label")
    p.add_argument("--model", required=True)
    p.add_argument("--frames", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--revision")
    p.add_argument("--device", default="gpu", choices=DEVICES)
    p.add_argument("--max-tokens", type=int, default=REPLY_MAX_TOKENS)
    a = p.parse_args(argv)
    own = (config(a.model, a.revision) or {}).get("model_file")
    if own:
        print(f"needs its own runner: {a.model} names its own model file {own!r}, which this labeller never "
              f"executes", file=sys.stderr)
        return hf_task.NEEDS_OWN_RUNNER
    ask = load(a.model, revision=a.revision, device=a.device)
    hf_task.vision_label(a.model, a.frames, a.prompt, a.out,
                         label=functools.partial(label_images, ask=ask, max_tokens=a.max_tokens))
    return 0


if __name__ == "__main__":
    sys.exit(main())
