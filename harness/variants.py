"""A model listing grouped into the variants a runner loads one of, for size and runtime. #947."""
from __future__ import annotations

import re
from dataclasses import dataclass

from harness import gguf

GIB = 1024 ** 3
GGUF, HF, MISTRAL, DIFFUSERS, COMFYUI, CHECKPOINT = (
    "gguf", "hf", "mistral", "diffusers", "comfyui", "checkpoint")
#: The words every detail written from a variant starts with; the sizing requeue keys on them.
MARK = "smallest variant "
#: model_type -> the engine that reads Mistral's consolidated layout for it (mlx-audio 0.5.3 sanitize()).
MISTRAL_READERS = {"voxtral_realtime": "mlx-audio"}
#: ComfyUI folders: the model, its encoders, its vae, an all-in-one checkpoint, and add-ons never required.
COMFY_CORE = {"diffusion_models", "unet"}
COMFY_ENCODERS = {"text_encoders", "clip"}
COMFY_VAE = {"vae"}
COMFY_WHOLE = {"checkpoints"}
COMFY_OPTIONAL = {"loras", "model_patches", "controlnet", "clip_vision", "upscale_models",
                  "style_models", "embeddings", "audio_encoders", "latent_upscale_models"}
COMFY_DIRS = COMFY_CORE | COMFY_ENCODERS | COMFY_VAE | COMFY_WHOLE | COMFY_OPTIONAL
#: A single checkpoint this many times smaller than the largest beside it is an add-on, not a variant.
LORA_FRACTION = 8
PRECISIONS = {"fp16", "bf16", "fp32", "fp8", "int8", "int4", "nf4"}
_SHARD = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.safetensors$", re.I)


@dataclass(frozen=True)
class Variant:
    format: str
    files: tuple[str, ...]
    bytes: int
    #: The runtime its files need beyond the lane's own engine, "" for none.
    runtime: str = ""

    def label(self) -> str:
        more = len(self.files) - 1
        return self.files[0] + (f" (+{more})" if more else "")

    def describe(self) -> str:
        n = len(self.files)
        return f"{self.label()}: {self.bytes / GIB:.1f} GiB of {n} weight file{'s' if n > 1 else ''}"


def _weights(siblings) -> list[tuple[str, int]]:
    from harness import downloads
    return [(str(s.get("rfilename", "")), int(s.get("size") or 0)) for s in siblings or []
            if str(s.get("rfilename", "")).lower().endswith(downloads.WEIGHT_SUFFIXES)]


def _variant(fmt: str, files, runtime: str = "") -> Variant:
    files = list(files)
    return Variant(fmt, tuple(n for n, _ in files), sum(s for _, s in files), runtime)


def _cuda_only(name: str) -> bool:
    from harness.inspect import _NEEDS_CUDA
    return bool(_NEEDS_CUDA.search(re.sub(r"[^A-Za-z0-9]+", " ", name)))


def _gguf(siblings, ceiling) -> tuple[Variant | None, set]:
    """The one GGUF fetch would take (gguf.choose under the ceiling, else the smallest), and every GGUF file."""
    singles = gguf._singles(siblings)
    sets: dict[str, list] = {}
    for f in siblings or []:
        m = gguf._PART.match(str(f.get("rfilename", "")))
        if m:
            sets.setdefault(m.group(1), []).append((str(f["rfilename"]), int(f.get("size") or 0)))
    complete = {stem: files for stem, files in sets.items() if stem in gguf.shard_sets(siblings)}
    seen = {str(f.get("rfilename", "")) for f in siblings or []
            if str(f.get("rfilename", "")).lower().endswith(".gguf")}
    pick = gguf.choose(siblings, ceiling) if ceiling else None
    if pick:
        return Variant(GGUF, (pick[0],), pick[1], "llamacpp"), seen
    options = [[s] for s in singles] + list(complete.values())
    if not options:
        return None, seen
    return _variant(GGUF, min(options, key=lambda fs: sum(s for _, s in fs)), "llamacpp"), seen


def _hf(top, has_config: bool) -> list[Variant]:
    """Transformers/MLX sets beside a top-level config.json: each complete model shard set, plus companions."""
    if not has_config:
        return []
    tensors = [(n, s) for n, s in top if n.lower().endswith(".safetensors")
               and not n.lower().startswith("consolidated")]
    pool = tensors or [(n, s) for n, s in top if n.lower().endswith((".bin", ".npz", ".pt", ".pth"))
                       and not n.lower().startswith("consolidated")]
    groups: dict[tuple, list] = {}
    for n, s in pool:
        m = _SHARD.match(n)
        key = (m.group(1).lower(), m.group(3)) if m else (n.lower().rsplit(".", 1)[0], "")
        groups.setdefault(key, []).append((n, s))
    models = [k for k in groups if k[0] in ("model", "pytorch_model")]
    if len(groups) <= 1 or not models:
        return [_variant(HF, pool)] if pool else []
    extra = [f for k, fs in groups.items() if k not in models for f in fs]
    return [_variant(HF, groups[k] + extra) for k in models]


def _precision(name: str) -> str:
    parts = name.rsplit("/", 1)[-1].lower().split(".")
    return parts[-2] if len(parts) >= 3 and parts[-2] in PRECISIONS else ""


def _diffusers(weights) -> list[Variant]:
    """One pipeline: per component folder, its smallest precision, safetensors over bin."""
    folders: dict[str, list] = {}
    for n, s in weights:
        if "/" in n:
            folders.setdefault(n.split("/", 1)[0], []).append((n, s))
    files = []
    for got in folders.values():
        tensors = [f for f in got if f[0].lower().endswith(".safetensors")] or got
        by: dict[str, list] = {}
        for f in tensors:
            by.setdefault(_precision(f[0]), []).append(f)
        files += min(by.values(), key=lambda fs: sum(s for _, s in fs))
    return [_variant(DIFFUSERS, files)] if files else []


def _comfy_role(name: str) -> str:
    dirs = {p.lower() for p in name.split("/")[:-1]}
    for role, names in (("core", COMFY_CORE), ("encoder", COMFY_ENCODERS), ("vae", COMFY_VAE),
                        ("whole", COMFY_WHOLE), ("optional", COMFY_OPTIONAL)):
        if dirs & names:
            return role
    return ""


def _smallest_runnable(files):
    """The smallest file, passing over a CUDA-only format while another is listed."""
    plain = [f for f in files if not _cuda_only(f[0])] or files
    return min(plain, key=lambda f: f[1])


def _comfy(weights) -> list[Variant]:
    roles: dict[str, list] = {}
    for f in weights:
        role = _comfy_role(f[0])
        if role:
            roles.setdefault(role, []).append(f)
    out = [_variant(COMFYUI, [_smallest_runnable([f])]) for f in roles.get("whole", [])]
    if roles.get("core"):
        out.append(_variant(COMFYUI, [_smallest_runnable(roles[r])
                                      for r in ("core", "encoder", "vae") if roles.get(r)]))
    return out


def _is_lora(name: str, size: int, largest: int) -> bool:
    words = set(re.split(r"[^a-z0-9]+", name.lower()))
    return "lora" in words or size * LORA_FRACTION < largest


def _checkpoints(top) -> list[Variant]:
    files = [(n, s) for n, s in top if n.lower().endswith((".safetensors", ".ckpt", ".pt", ".pth"))
             and not n.lower().startswith("consolidated")]
    largest = max((s for _, s in files), default=0)
    models = [f for f in files if not _is_lora(f[0], f[1], largest)] or files
    return [_variant(CHECKPOINT, [f], "cuda" if _cuda_only(f[0]) else "") for f in models]


def variants(siblings, ceiling: int | None = None, model_type: str = "") -> list[Variant]:
    """Every variant the listing holds; GGUF quants collapse to the one fetch would take under `ceiling`."""
    weights = [(n, s) for n, s in _weights(siblings) if s > 0]
    names = {str(s.get("rfilename", "")).lower() for s in siblings or []}
    top = [(n, s) for n, s in weights if "/" not in n]
    out: list[Variant] = []
    one, gguf_files = _gguf(siblings, ceiling)
    if one:
        out.append(one)
    top = [f for f in top if f[0] not in gguf_files]
    consolidated = [f for f in top if f[0].lower().startswith("consolidated")]
    if not (consolidated and model_type in MISTRAL_READERS):
        out += _hf(top, "config.json" in names)
    if consolidated:
        out.append(_variant(MISTRAL, consolidated, "" if model_type in MISTRAL_READERS else "vllm"))
    nested = [f for f in weights if "/" in f[0] and f[0] not in gguf_files]
    if "model_index.json" in names:
        out += _diffusers(nested)
    else:
        out += _comfy(nested)
    if not out and "config.json" not in names and "model_index.json" not in names:
        out += _checkpoints(top)
    return out


def weight_bytes(siblings) -> int:
    return sum(s for _, s in _weights(siblings))


def layout(siblings) -> str:
    """The folders and suffixes of weights no variant takes, for an until a reader can act on."""
    where = sorted({(n.split("/", 1)[0] + "/" if "/" in n else "") + "*." + n.rsplit(".", 1)[-1].lower()
                    for n, _ in _weights(siblings)})
    return ",".join(where[:4]) + (f",+{len(where) - 4}" if len(where) > 4 else "")


def pick(found: list[Variant], has=lambda runtime: True) -> Variant | None:
    """The smallest variant with a runtime `has`, else the smallest of all; None for no variants."""
    runnable = [v for v in found if not v.runtime or has(v.runtime)] or found
    return min(runnable, key=lambda v: v.bytes) if runnable else None


def needs(found: list[Variant]) -> str:
    """The one runtime every variant needs, or "" when one needs none or they differ."""
    runtimes = {v.runtime for v in found}
    return runtimes.pop() if len(runtimes) == 1 else ""


def download_files(siblings, chosen: Variant) -> list[str] | None:
    """The files fetch takes for `chosen`: its weights and every non-weight file; None when it is the only variant."""
    from harness import downloads
    names = [str(s.get("rfilename", "")) for s in siblings or []]
    weights = [n for n in names if n.lower().endswith(downloads.WEIGHT_SUFFIXES)]
    if set(weights) <= set(chosen.files):
        return None
    return [n for n in names if n in chosen.files or not n.lower().endswith(downloads.WEIGHT_SUFFIXES)]
