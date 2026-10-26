"""Frames through a private llama-server that loads a GGUF and its mmproj projector (#1282).

Never the router: one loopback server per run, started with -m and --mmproj, stopped when the run ends.
"""
from __future__ import annotations

import base64
import contextlib
import os
import socket
import subprocess
import time
from pathlib import Path

from harness import gguf

#: mmproj precisions preferred in turn: the projector is small, so the closest to the source wins.
MMPROJ_PREFERRED = ("f16", "bf16", "q8_0", "f32")
_popen = subprocess.Popen


class _Httpx:
    def get(self, url, timeout=None):
        import httpx
        return httpx.get(url, timeout=timeout)

    def post(self, url, json=None, timeout=None):
        import httpx
        return httpx.post(url, json=json, timeout=timeout)


_http = _Httpx()


def _gguf_names(siblings) -> list[tuple[str, int]]:
    return [(str(s.get("rfilename", "")), int(s.get("size") or 0)) for s in siblings or []
            if str(s.get("rfilename", "")).lower().endswith(".gguf") and "/" not in str(s.get("rfilename", ""))]


def pick(siblings, quant: str = "", ceiling: int = 1 << 62) -> tuple[str, str]:
    """(model GGUF, mmproj GGUF) in a listing: the named quant, else gguf.choose's; the projector by precision."""
    projectors = [(n, s) for n, s in _gguf_names(siblings) if n.lower().startswith("mmproj")]
    if not projectors:
        raise ValueError("the repo ships no mmproj projector, so llama-server cannot read an image with it")
    if quant:
        named = [n for n, _ in _gguf_names(siblings) if not n.lower().startswith("mmproj")
                 and quant.lower() in n.lower()]
        if not named:
            raise ValueError(f"no GGUF in the repo is quant {quant}")
        model = min(named, key=len)
    else:
        got = gguf.choose(siblings, ceiling)
        if not got:
            raise ValueError("no single-file GGUF in the repo fits")
        model = got[0]
    for want in MMPROJ_PREFERRED:
        for name, _ in projectors:
            if want in name.lower():
                return model, name
    return model, min(projectors, key=lambda p: p[1])[0]


def files(repo: str, quant: str = "", revision: str | None = None) -> tuple[Path, Path]:
    """The model and projector files of a hub repo, downloaded into the hub cache if absent."""
    from huggingface_hub import HfApi, hf_hub_download
    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    siblings = [{"rfilename": s.rfilename, "size": s.size or 0} for s in info.siblings or []]
    model, mmproj = pick(siblings, quant)
    return (Path(hf_hub_download(repo, model, revision=revision)),
            Path(hf_hub_download(repo, mmproj, revision=revision)))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def argv_for(model: Path, mmproj: Path, port: int, device: str = "gpu", ctx: int | None = None) -> list[str]:
    from evals.vision import LLAMACPP_CTX
    ctx = LLAMACPP_CTX if ctx is None else ctx
    place = ["-ngl", "0", "--device", "none", "--no-mmproj-offload"] if device == "cpu" else ["-ngl", "999"]
    return [os.environ.get("LLAMACPP_BIN", "llama-server"), "-m", str(model), "--mmproj", str(mmproj),
            "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx), "-np", "1", "--offline",
            "--no-webui", *place]


@contextlib.contextmanager
def serve(model: Path, mmproj: Path, device: str = "gpu", log=None):
    """A private llama-server on a free loopback port; yields its base URL and stops it on the way out."""
    from evals.vision import LLAMACPP_START_S
    port = _free_port()
    proc = _popen(argv_for(model, mmproj, port, device), stdout=log or subprocess.DEVNULL,
                  stderr=subprocess.STDOUT if log else subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        give_up = time.monotonic() + LLAMACPP_START_S
        last = "no answer"
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"llama-server exited {proc.poll()} before it answered")
            try:
                status = _http.get(f"{base}/health", timeout=5).status_code
                if status == 200:
                    break
                last = f"HTTP {status}"
            except Exception as exc:  # noqa: BLE001  any refusal while it loads is "not yet"
                last = repr(exc)
            if time.monotonic() > give_up:
                raise RuntimeError(f"llama-server did not answer its health check within {LLAMACPP_START_S} s "
                                   f"(vision_llamacpp_start_s); last: {last}")
            time.sleep(1)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def ask(base: str, image: str, prompt: str, max_tokens: int, timeout: float) -> tuple[str, bool]:
    """One frame as an image_url chat message; (reply, cut at the budget)."""
    data = base64.b64encode(Path(image).read_bytes()).decode("ascii")
    body = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
        {"type": "text", "text": prompt}]}],
        "temperature": 0, "max_tokens": max_tokens, "seed": 0}
    got = _http.post(f"{base}/v1/chat/completions", json=body, timeout=timeout)
    got.raise_for_status()
    choice = got.json()["choices"][0]
    return str(choice["message"].get("content") or "").strip(), choice.get("finish_reason") == "length"


def label_images(repo: str, images, prompt: str, *, quant: str = "", revision: str | None = None,
                 device: str = "gpu", log=None):
    from evals.vision import REPLY_MAX_TOKENS, REQUEST_TIMEOUT_S
    images = list(images)
    if not images:
        return
    model, mmproj = files(repo, quant, revision)
    with serve(model, mmproj, device, log=log) as base:
        for image in images:
            yield ask(base, image, prompt, REPLY_MAX_TOKENS, REQUEST_TIMEOUT_S)
