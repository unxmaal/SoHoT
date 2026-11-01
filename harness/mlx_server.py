"""mlx_lm.server with a listen backlog that holds a burst of concurrent clients. #542."""
from __future__ import annotations

import http.server
import json
import sys
import threading
import urllib.error
import urllib.request

#: What this wraps; serving.DEFAULT names it on receipts.
WRAPS = "mlx_lm.server"

#: socketserver's default is 5; past it macOS resets the connection before mlx_lm sees it.
BACKLOG = 256

#: GET answers {"model": the repo id or path it holds, or null}; stock mlx_lm.server cannot. #588.
LOADED_PATH = "/sohot/loaded"

#: mlx_lm.server's own GET: 200 while its generation thread lives, 503 once it died (#912).
HEALTH_PATH = "/health"

#: Distinct KV caches held; mlx-lm's default is 10, the count it held when Metal's 499000-buffer limit killed it (#912).
PROMPT_CACHE_SIZE = 4
#: Bytes of KV cache held; mlx-lm leaves it unbounded.
PROMPT_CACHE_BYTES = "8GB"
#: Seconds a swap back to the boot model may take: its load plus one token. #1082.
SWAP_TIMEOUT_S = 120.0

try:
    from mlx_lm.server import main as ENTRY
except ImportError:  # pragma: no cover - mlx-lm is darwin-only
    ENTRY = None


def raise_backlog(n: int = BACKLOG) -> None:
    """mlx_lm.server builds http.server.ThreadingHTTPServer, so its listen() reads this."""
    http.server.ThreadingHTTPServer.request_queue_size = n


def loaded_model(provider) -> str | None:
    """The model mlx_lm's ModelProvider holds now, or None."""
    key = getattr(provider, "model_key", None)
    if not key:
        return None
    return (getattr(provider, "_model_map", None) or {}).get(key[0], key[0])


def boot_model(provider) -> str | None:
    """The --model the server started with, which a swap off any other model goes back to."""
    got = getattr(getattr(provider, "cli_args", None), "model", None)
    return str(got) if got else None


def serve_loaded(handler) -> None:
    """Answer LOADED_PATH on `handler`'s GET with what it holds, its boot model and the POSTs in flight (#1157)."""
    original, posting = handler.do_GET, getattr(handler, "do_POST", None)
    lock, in_flight = threading.Lock(), [0]

    def do_POST(self):
        with lock:
            in_flight[0] += 1
        try:
            return posting(self)
        finally:
            with lock:
                in_flight[0] -= 1

    def do_GET(self):
        if self.path != LOADED_PATH:
            return original(self)
        provider = self.response_generator.model_provider
        body = json.dumps({"model": loaded_model(provider), "boot": boot_model(provider),
                           "in_flight": in_flight[0]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return None

    handler.do_GET = do_GET
    if posting is not None:
        handler.do_POST = do_POST


def cache_caps(argv: list[str]) -> list[str]:
    """`argv` with the prompt cache capped, unless the caller set a cap itself."""
    out = list(argv)
    for flag, value in (("--prompt-cache-size", PROMPT_CACHE_SIZE), ("--prompt-cache-bytes", PROMPT_CACHE_BYTES)):
        if not any(a == flag or a.startswith(flag + "=") for a in out):
            out += [flag, str(value)]
    return out


def generating(base: str, timeout: float, opener=urllib.request.urlopen) -> bool | None:
    """True when the server at `base` can generate, False when it answers that it cannot, None when it did not answer."""
    try:
        with opener(base.rstrip("/") + HEALTH_PATH, timeout=timeout) as r:
            return r.status == 200
    except urllib.error.HTTPError as exc:
        return False if exc.code == 503 else None
    except (OSError, ValueError):
        return None


def held(base: str, timeout: float, opener=urllib.request.urlopen) -> str | None:
    """The model the server at `base` holds now, None when it holds none or did not answer."""
    try:
        with opener(base.rstrip("/") + LOADED_PATH, timeout=timeout) as r:
            got = json.loads(r.read() or b"{}").get("model")
    except (OSError, ValueError, AttributeError):
        return None
    return str(got) if got else None


def activity(base: str, timeout: float, opener=urllib.request.urlopen) -> dict | None:
    """{"model", "boot", "in_flight"} from the server at `base`, None when it did not answer; old servers lack the last two."""
    try:
        with opener(base.rstrip("/") + LOADED_PATH, timeout=timeout) as r:
            got = json.loads(r.read() or b"{}")
    except (OSError, ValueError, AttributeError):
        return None
    return {k: got.get(k) for k in ("model", "boot", "in_flight")} if isinstance(got, dict) else None


def _swap_to_boot(base: str, timeout: float, opener) -> None:
    """A one-token request naming no model: mlx_lm drops what it holds and loads its --model, the server's own path."""
    body = json.dumps({"messages": [{"role": "user", "content": "ok"}], "max_tokens": 1}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with opener(req, timeout=timeout) as r:
        r.read()


def release(model: str, why: str, *, base: str = "", keep=None, timeout: float | None = None,
            opener=urllib.request.urlopen, say=print) -> bool:
    """Swap the mlx server off `model` when it still holds it and nothing protects it; True when it let go. #1082."""
    from harness import serving
    base = base or serving.MLX_URL
    timeout = SWAP_TIMEOUT_S if timeout is None else timeout
    if not model or held(base, timeout, opener) != model:
        return False
    try:
        if keep is None:
            from harness import router
            keep = router.protected()
    except Exception as exc:  # noqa: BLE001 - unknown protection means nothing is free to unload
        say(f"  mlx: kept {model}: the lane defaults could not be read ({exc})")
        return False
    if model in keep:
        return False
    from harness import cuts
    try:
        with cuts.timeout("mlx_swap_timeout", f"unloading {model}", value=timeout):
            _swap_to_boot(base, timeout, opener)
    except (OSError, ValueError) as exc:
        say(f"  mlx: could not unload {model}: {exc}")
        return False
    if held(base, timeout, opener) == model:
        say(f"  mlx: kept {model}: it is the server's own boot model")
        return False
    say(f"  mlx: unloaded {model} ({why})")
    return True


def release_spec(spec: str, why: str, **kw) -> bool:
    """release() for the model a candidate spec loads into the mlx server, if it is the one held."""
    from harness import methods, serving
    base = kw.pop("base", "") or serving.MLX_URL
    model = held(base, kw.get("timeout") or SWAP_TIMEOUT_S, kw.get("opener", urllib.request.urlopen))
    bare = (methods.base_of(spec) if methods.is_method(spec) else spec).partition(",")[0].strip()
    if not model or bare != model:
        return False
    return release(model, why, base=base, **kw)


def main() -> None:
    sys.argv[1:] = cache_caps(sys.argv[1:])
    raise_backlog()
    if ENTRY is None:
        raise SystemExit(f"{WRAPS} is not installed")
    from mlx_lm.server import APIHandler
    serve_loaded(APIHandler)
    ENTRY()


if __name__ == "__main__":
    main()
