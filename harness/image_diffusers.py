"""The image lane's generator through diffusers, on whatever accelerator is here.

It is a command line rather than a library call for one reason:
harness/engines.py treats an engine as data, a spec string that becomes an
argv, and the CLI and the eval suite then issue byte-identical commands.
mflux-generate has that shape and so does this.

IT WAS CUDA-ONLY, and was named image_cuda for it. That was not a fact about
diffusers, it was the CUDA machine being the only place anyone had tried: this
file selected `cuda` or fell back to refusing, so on Apple Silicon the lane had
exactly one engine and mflux had never faced a challenger. torch runs on Metal
through mps, and the svg lane's audit recorded that path as viable here two
weeks before anything used it.

IT STILL REFUSES THE CPU unless told to. SDXL on a CPU is minutes per image
where an accelerator is seconds, and a lane that silently took that path would
report the model as slow rather than the machine as misconfigured. The same
reasoning as the transcription server's device message.

A .json sidecar goes beside every PNG, holding the model, the seed and the
step count. mflux writes one under --metadata for the same reason: a result
from three weeks ago is only reproducible if it says what produced it.
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

from harness.torch_device import BF16, FP16, accelerator, declared_dtype, load_dtype, other_half

DEFAULT_SIZE = 512
#: Steps and guidance each distilled family's own model card names; any other model gets its pipeline's defaults. #691.
FAMILY_SAMPLING = {
    "sdxl_turbo": {"steps": 4, "guidance": 0.0},
    "z_image_turbo": {"steps": 9, "guidance": 0.0},
    "stable_diffusion_3_5_large_turbo": {"steps": 4, "guidance": 0.0},
}


def family(model: str) -> dict:
    """The sampling a model's family card names, by the longest family key in its repo name, else {}."""
    tail = model.rsplit("/", 1)[-1].lower().replace("-", "_").replace(".", "_")
    keys = [k for k in FAMILY_SAMPLING if k in tail]
    return FAMILY_SAMPLING[max(keys, key=len)] if keys else {}


def sampling(model: str, steps: int | None, guidance: float | None) -> dict:
    """What to pass the pipeline: the caller's values, else the family's, else nothing. #401, #691."""
    fam = family(model)
    steps = fam.get("steps") if steps is None else steps
    guidance = fam.get("guidance") if guidance is None else guidance
    out = {}
    if steps is not None:
        out["num_inference_steps"] = steps
    if guidance is not None:
        out["guidance_scale"] = guidance
    return out


def pipeline_default(pipe, name: str):
    p = inspect.signature(pipe.__call__).parameters.get(name)
    return None if p is None or p.default is inspect.Parameter.empty else p.default


def metadata(args, pipe, device: str, torch_version: str) -> dict:
    """The sidecar beside an image, with the steps and guidance it was actually generated at. #691."""
    used = sampling(args.model, args.steps, args.guidance)
    return {
        "model": args.model,
        "prompt": args.prompt,
        "steps": used.get("num_inference_steps", pipeline_default(pipe, "num_inference_steps")),
        "guidance": used.get("guidance_scale", pipeline_default(pipe, "guidance_scale")),
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "device": device,
        "torch": torch_version,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="image-diffusers", description=__doc__)
    p.add_argument("--model", required=True,
                   help="a diffusers repo id, e.g. stabilityai/sdxl-turbo")
    p.add_argument("--prompt", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--width", type=int, default=DEFAULT_SIZE)
    p.add_argument("--height", type=int, default=DEFAULT_SIZE)
    p.add_argument("--guidance", type=float, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--allow-cpu", action="store_true",
                   help="generate without a card, which takes minutes")
    return p.parse_args(argv)


def snapshot(model: str):
    """The local directory a repo id or path resolves to, without the network, else None. #1013."""
    if Path(model).is_dir():
        return Path(model)
    # Not snapshot_download(local_files_only): it refuses a snapshot fetched as one variant as incomplete.
    try:
        from huggingface_hub import try_to_load_from_cache
        got = try_to_load_from_cache(model, "model_index.json")
    except Exception:  # noqa: BLE001 - any miss means "no declaration to read"
        return None
    return Path(got).parent if isinstance(got, str) else None


def _pipeline(model: str, device: str, dtype: str):
    import diffusers
    import torch

    # `variant="fp16"` asks for a separate set of files many repos do not publish, so only CUDA at fp16 asks.
    pipe = load(diffusers, model, torch_dtype=getattr(torch, dtype),
                variant="fp16" if device == "cuda" and dtype == FP16 else None,
                safety_checker=None)
    return pipe.to(device)


def _release(torch, device: str) -> None:
    import gc
    gc.collect()
    if device == "mps":
        torch.mps.empty_cache()
    elif device == "cuda":
        torch.cuda.empty_cache()


def unsupported(exc: BaseException, dtype: str) -> bool:
    """An error saying this device cannot run bf16, so fp16 may. #1013."""
    low = str(exc).lower()
    return dtype == BF16 and ("bfloat16" in low or "bf16" in low)


def render(args, device: str, torch, first: str, build=None):
    """The image, the pipeline and the dtype that drew it, retrying the other half once on a blank canvas or a bf16 refusal. #1013."""
    from harness.checks.image import blank
    build = build or _pipeline
    tried: list[str] = []
    dtypes = [first] + ([other_half(first)] if other_half(first) else [])
    for i, dtype in enumerate(dtypes):
        last = i == len(dtypes) - 1
        pipe = generator = None
        if args.seed is not None:
            generator = torch.Generator(device=device).manual_seed(args.seed)
        try:
            pipe = build(args.model, device, dtype)
            image = pipe(prompt=args.prompt, width=args.width, height=args.height,
                         generator=generator,
                         **sampling(args.model, args.steps, args.guidance)).images[0]
        except (RuntimeError, TypeError, ValueError) as exc:
            if last or not unsupported(exc, dtype):
                raise
            print(f"image-diffusers: {dtype} failed on {device} ({exc}); retrying at {dtypes[i + 1]}",
                  file=sys.stderr)
            tried.append(dtype)
            pipe = None
            _release(torch, device)
            continue
        if last or not blank(image):
            return image, pipe, dtype, tried
        print(f"image-diffusers: blank image at {dtype}; retrying at {dtypes[i + 1]}", file=sys.stderr)
        tried.append(dtype)
        del pipe, image
        _release(torch, device)
    raise AssertionError("unreachable")


def load(diffusers, model: str, **kw):
    """AutoPipeline's table lags the library: PRXPixelPipeline ships in 0.40
    and is not in it. model_index.json names the class either way. #380."""
    try:
        return diffusers.AutoPipelineForText2Image.from_pretrained(model, **kw)
    except ValueError as exc:
        if "can't find a pipeline" not in str(exc):
            raise
        return diffusers.DiffusionPipeline.from_pretrained(model, **kw)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    import torch
    device = accelerator(torch)
    if not device:
        if not args.allow_cpu:
            print("image-diffusers: no cuda device and no mps device. "
                  "Generating on the CPU takes minutes per image and would "
                  "read as a slow model rather than a machine without an "
                  "accelerator; pass --allow-cpu to do it anyway.",
                  file=sys.stderr)
            return 2
        device = "cpu"

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    first = load_dtype(declared_dtype(snapshot(args.model)), device)
    image, pipe, dtype, tried = render(args, device, torch, first)
    image.save(out)

    meta = {**metadata(args, pipe, device, torch.__version__), "dtype": dtype}
    if tried:
        meta["retried_from"] = tried
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
