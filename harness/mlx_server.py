"""mlx_lm.server with a listen backlog that holds a burst of concurrent clients. #542."""
from __future__ import annotations

import http.server
import json

#: What this wraps; serving.DEFAULT names it on receipts.
WRAPS = "mlx_lm.server"

#: socketserver's default is 5; past it macOS resets the connection before mlx_lm sees it.
BACKLOG = 256

#: GET answers {"model": the repo id or path it holds, or null}; stock mlx_lm.server cannot. #588.
LOADED_PATH = "/sohot/loaded"

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


def serve_loaded(handler) -> None:
    """Answer LOADED_PATH on `handler`'s GET; every other path goes to its own do_GET."""
    original = handler.do_GET

    def do_GET(self):
        if self.path != LOADED_PATH:
            return original(self)
        body = json.dumps({"model": loaded_model(
            self.response_generator.model_provider)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return None

    handler.do_GET = do_GET


def main() -> None:
    raise_backlog()
    if ENTRY is None:
        raise SystemExit(f"{WRAPS} is not installed")
    from mlx_lm.server import APIHandler
    serve_loaded(APIHandler)
    ENTRY()


if __name__ == "__main__":
    main()
