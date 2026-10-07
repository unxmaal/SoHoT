"""mlx_lm.server with a listen backlog that holds a burst of concurrent clients. #542."""
from __future__ import annotations

import http.server

#: What this wraps; serving.DEFAULT names it on receipts.
WRAPS = "mlx_lm.server"

#: socketserver's default is 5; past it macOS resets the connection before mlx_lm sees it.
BACKLOG = 256

try:
    from mlx_lm.server import main as ENTRY
except ImportError:  # pragma: no cover - mlx-lm is darwin-only
    ENTRY = None


def raise_backlog(n: int = BACKLOG) -> None:
    """mlx_lm.server builds http.server.ThreadingHTTPServer, so its listen() reads this."""
    http.server.ThreadingHTTPServer.request_queue_size = n


def main() -> None:
    raise_backlog()
    if ENTRY is None:
        raise SystemExit(f"{WRAPS} is not installed")
    ENTRY()


if __name__ == "__main__":
    main()
