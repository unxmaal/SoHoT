"""MCP and audio servers bind loopback by default; bound wider, they demand the gateway key. #510."""
from __future__ import annotations

import ipaddress
import json
import secrets
import sys

from harness import gateway_key

LOOPBACK_HOST = "127.0.0.1"
MESSAGE = f"gateway key missing or wrong: {gateway_key.HINT}"


def exposed(host: str) -> bool:
    """Whether binding `host` lets another machine connect."""
    if host == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


def matches(given, key) -> bool:
    """Constant-time; no key refuses everyone."""
    if not isinstance(given, str) or not isinstance(key, str) or not given or not key:
        return False
    return secrets.compare_digest(given.encode("utf-8"), key.encode("utf-8"))


def bearer(scope) -> str:
    for name, value in scope.get("headers") or ():
        if name.lower() == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            return token.strip() if scheme.lower() == "bearer" else ""
    return ""


class KeyRequired:
    """ASGI wrapper: every HTTP or websocket request carries `Authorization: Bearer <key>`."""

    def __init__(self, app, key: str):
        if not key:
            raise ValueError("a LAN-exposed server needs a gateway key; `soh gateway key` makes one")
        self.app = app
        self._key = key

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or matches(bearer(scope), self._key):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        body = json.dumps({"error": MESSAGE}).encode()
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                                (b"www-authenticate", b'Bearer realm="sohot"')]})
        await send({"type": "http.response.body", "body": body})


def guard(app, host: str, store=None):
    """`app` as is on loopback; behind the gateway key when `host` reaches the LAN."""
    if not exposed(host):
        return app
    return KeyRequired(app, gateway_key.ensure(store))


def serve(target: str, host: str, port: int) -> None:
    """Run the ASGI app at `module:attr` under uvicorn, guarded for `host`."""
    import importlib

    import uvicorn
    module, _, attr = target.partition(":")
    app = getattr(importlib.import_module(module), attr)
    uvicorn.run(guard(app, host), host=host, port=port, loop="asyncio")


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m harness.lan_auth")
    ap.add_argument("target", help="module:app, e.g. mlx_audio.server:app")
    ap.add_argument("--host", default=LOOPBACK_HOST)
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args(argv)
    serve(a.target, a.host, a.port)


if __name__ == "__main__":
    main(sys.argv[1:])
