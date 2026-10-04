"""One GGUF file per repo, for llama-server's router. See README, #295."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

#: First match wins; otherwise the largest file under the ceiling.
PREFERRED = ("q4_k_m", "q4_k_s", "iq4_xs", "q4_0", "q5_k_m", "q5_k_s")
_SPLIT = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)


def models_dir() -> Path:
    """Where llama-server's router reads (scripts/serve-llamacpp.sh)."""
    raw = os.environ.get("LLAMACPP_MODELS_DIR")
    if raw:
        return Path(raw)
    hf = os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface"
    return Path(hf) / "gguf"


def _servable(f: dict) -> bool:
    name = str(f.get("rfilename", ""))
    return (name.lower().endswith(".gguf") and "/" not in name
            and not name.lower().startswith("mmproj")
            and "imatrix" not in name.lower()
            and not _SPLIT.search(name))


def smallest(siblings) -> int:
    """The smallest file the router could serve, or 0 if none."""
    return min((int(f.get("size") or 0) for f in siblings or []
                if _servable(f) and f.get("size")), default=0)


def only(siblings) -> bool:
    """GGUF weights and nothing MLX or torch could load instead."""
    names = [str(f.get("rfilename", "")).lower() for f in siblings or []]
    return (any(n.endswith(".gguf") for n in names)
            and not any(n.endswith(".safetensors") for n in names))


def choose(siblings, ceiling: int) -> tuple[str, int] | None:
    """The file to fetch: (name, bytes), or None if none fits."""
    fits = [(str(f["rfilename"]), int(f.get("size") or 0))
            for f in siblings or [] if _servable(f)]
    fits = [(n, s) for n, s in fits if 0 < s <= ceiling]
    for quant in PREFERRED:
        for name, size in fits:
            if quant in name.lower():
                return name, size
    return max(fits, key=lambda f: f[1]) if fits else None


def _manifest() -> Path:
    from harness import paths
    return paths.home() / "gguf-sources.json"


def _load() -> dict:
    try:
        return json.loads(_manifest().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember(repo: str, filename: str) -> None:
    got = _load()
    got[repo] = filename
    _manifest().parent.mkdir(parents=True, exist_ok=True)
    _manifest().write_text(json.dumps(got, indent=1, sort_keys=True),
                           encoding="utf-8")


def path_of(repo: str, adopt: bool = False) -> Path | None:
    """`adopt` only from a caller that knows the repo is text-lane. #303."""
    name = _load().get(repo) or (_adopt_from_hub(repo) if adopt else "")
    if not name:
        return None
    path = models_dir() / name
    return path if path.exists() else None


def _adopt_from_hub(repo: str) -> str:
    """A GGUF-only repo fetched whole before #296: link its file in. #301."""
    hf = os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface"
    snaps = Path(hf) / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots"
    if not snaps.is_dir():
        return ""
    from harness import inspect as ins
    for snap in sorted(snaps.iterdir()):
        files = [{"rfilename": f.name, "size": f.stat().st_size}
                 for f in snap.iterdir() if f.is_file()]
        pick = choose(files, ins.ceiling_bytes()) if only(files) else None
        if pick:
            models_dir().mkdir(parents=True, exist_ok=True)
            link = models_dir() / pick[0]
            if not link.exists():
                link.symlink_to((snap / pick[0]).resolve())
            remember(repo, pick[0])
            return pick[0]
    return ""


def fetched(repo: str, adopt: bool = False) -> str | None:
    """The stem llama-server's router serves this repo under, if on disk."""
    path = path_of(repo, adopt)
    return path.name[:-len(".gguf")] if path else None


def refresh_router() -> None:
    """Restart the eval server so its router sees a new file. #319."""
    import subprocess
    import sys
    if sys.platform != "darwin":
        return
    script = Path(__file__).resolve().parents[1] / "scripts" / "launchd.sh"
    subprocess.run([str(script), "restart", "eval"], check=False)


def download(repo: str, filename: str, hf_download=None, refresh=None) -> str:
    if hf_download is None:
        from huggingface_hub import hf_hub_download

        def hf_download(repo, filename, local_dir):
            return hf_hub_download(repo_id=repo, filename=filename,
                                   local_dir=local_dir)
    models_dir().mkdir(parents=True, exist_ok=True)
    where = hf_download(repo, filename, str(models_dir()))
    remember(repo, filename)
    (refresh or refresh_router)()
    return str(where)
