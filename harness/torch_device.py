"""Which accelerator torch should use, asked once.

Both diffusers generators asked `torch.cuda.is_available()` and nothing else,
so "no card" and "no Apple GPU" were the same answer and the image lane had
exactly one engine on Apple Silicon for months. Fixing that in one file and
not the other is how this repo has collected four separate copies of "which
engines exist"; RULE #237 says the fix is a read, not more care.

Separate from harness/engines.py because these run inside the diffusers venv,
which has torch and has no need of the rest of this package.
"""
from __future__ import annotations


def accelerator(torch) -> str:
    """The device to generate on, or "" when there is no accelerator.

    Passed the module rather than importing it, so a test can pin the answer:
    `torch.cuda.is_available()` reads the machine, and a test that reads the
    machine tests the machine (RULE #249).
    """
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return ""


#: Accelerators that should load half precision; fp32 on a 32 GB unified machine doubles the working set for nothing.
HALF = ("cuda", "mps")

BF16, FP16, FP32 = "bfloat16", "float16", "float32"
#: The half precision a device loads when the repo names none: bf16 keeps fp32's range on Metal, fp16 stays CUDA's. #1013.
DEFAULT_HALF = {"mps": BF16, "cuda": FP16}
_NAMED = {"bfloat16": BF16, "bf16": BF16, "float16": FP16, "fp16": FP16, "half": FP16}
_STORED = {"BF16": BF16, "F16": FP16}
#: A safetensors header past this is not one; reading it would be reading weights.
MAX_HEADER = 1 << 26


def _header_dtypes(path) -> set[str]:
    import json
    import struct
    try:
        with open(path, "rb") as fh:
            n = struct.unpack("<Q", fh.read(8))[0]
            if n > MAX_HEADER:
                return set()
            header = json.loads(fh.read(n))
    except (OSError, ValueError, struct.error):
        return set()
    if not isinstance(header, dict):
        return set()
    return {_STORED[v["dtype"]] for k, v in header.items()
            if k != "__metadata__" and isinstance(v, dict) and v.get("dtype") in _STORED}


def _config_dtypes(path) -> set[str]:
    import json
    from pathlib import Path
    try:
        got = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(got, dict):
        return set()
    return {_NAMED[v] for v in (got.get("torch_dtype"), got.get("dtype")) if isinstance(v, str) and v in _NAMED}


def declared_dtype(root) -> str:
    """The half precision a snapshot's configs or stored weights name, bf16 over fp16, else "". #1013."""
    from pathlib import Path
    if root is None or not Path(root).is_dir():
        return ""
    root = Path(root)
    named: set[str] = set()
    for config in [root / "config.json", *root.glob("*/config.json")]:
        named |= _config_dtypes(config)
    for weights in [*root.glob("*.safetensors"), *root.glob("*/*.safetensors")]:
        named |= _header_dtypes(weights)
    return BF16 if BF16 in named else FP16 if FP16 in named else ""


def load_dtype(declared: str, device: str, default: str = "") -> str:
    """The dtype to load on `device`: what the repo declares, else `default` or the device's half, fp32 off an accelerator. #1013."""
    if device not in HALF:
        return FP32
    return declared or default or DEFAULT_HALF.get(device, FP16)


def other_half(dtype: str) -> str:
    """The half precision to retry at when `dtype` rendered nothing, or "" off the halves. #1013."""
    return {BF16: FP16, FP16: BF16}.get(dtype, "")
