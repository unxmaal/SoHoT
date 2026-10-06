"""The gateway's master key: one per machine, never in the repo. #482.

The gateway listens on the LAN, so it demands a key. The Mac keeps it in the
login Keychain, everything else in a 0600 file under LOCALHARNESS_HOME, and
SOHOT_GATEWAY_KEY overrides both (a client of another machine's gateway).
"""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ENV_VAR = "SOHOT_GATEWAY_KEY"
#: "file" forces the file store on a Mac.
STORE_ENV = "SOHOT_GATEWAY_STORE"
SERVICE = "localharness-gateway"
FILE_NAME = "gateway.key"
HINT = ("`soh gateway key` prints this machine's gateway key; a client of "
        "another machine's gateway sets SOHOT_GATEWAY_KEY to that machine's")


class Keychain:
    """The macOS login Keychain, through `security`."""

    def __init__(self, run=subprocess.run):
        self.run = run

    def get(self) -> str:
        r = self.run(["security", "find-generic-password", "-s", SERVICE, "-w"],
                     capture_output=True, text=True)
        return (r.stdout or "").strip() if r.returncode == 0 else ""

    def set(self, value: str) -> None:
        # `security -i` reads its command from stdin, so the key is never in argv.
        account = os.environ.get("USER") or "sohot"
        r = self.run(["security", "-i"], capture_output=True, text=True,
                     input=f"add-generic-password -U -a {account} -s {SERVICE} "
                           f"-w {value}\n")
        if r.returncode != 0:
            raise RuntimeError(f"could not store the gateway key: {r.stderr.strip()}")


class FileStore:
    """A file only its owner can read."""

    def __init__(self, path):
        self.path = Path(path)

    def get(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def set(self, value: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)


def platform_store(platform: str | None = None, which=shutil.which):
    """Keychain on a Mac that has `security`, else the file under the home."""
    from harness import paths
    platform = platform or sys.platform
    if (platform == "darwin" and which("security")
            and os.environ.get(STORE_ENV) != "file"):
        return Keychain()
    return FileStore(paths.home() / FILE_NAME)


def default_store():
    return platform_store()


_cache: dict = {}


def _stored(store) -> str:
    if store is not None:
        return store.get()
    if "key" not in _cache:
        _cache["key"] = default_store().get()
    return _cache["key"]


def key(environ=None, store=None) -> str:
    """The key a client sends; "" when this machine has none."""
    environ = os.environ if environ is None else environ
    return (environ.get(ENV_VAR) or "").strip() or _stored(store)


def headers(environ=None, store=None) -> dict:
    """The Authorization header for a gateway request, {} without a key."""
    k = key(environ, store)
    return {"Authorization": f"Bearer {k}"} if k else {}


def refused(status: int, body: str = "", sent: str = "") -> bool:
    """Whether a gateway reply is a key refusal: 401 since #501, 400/500 from LiteLLM before it."""
    if status in (401, 403):
        return True
    if status == 400 and "no_db_connection" in (body or ""):
        return True
    return status == 500 and not sent


def generate() -> str:
    return "sk-" + secrets.token_urlsafe(32)


def ensure(store=None) -> str:
    """The stored key, generated and stored first if there is none."""
    store = store or default_store()
    got = store.get()
    if not got:
        got = generate()
        store.set(got)
    _cache.pop("key", None)
    return got


def rotate(store=None) -> str:
    store = store or default_store()
    new = generate()
    store.set(new)
    _cache.pop("key", None)
    return new


if __name__ == "__main__":
    # ensure: serve-gateway.sh, creating the key on first start. show: a client.
    verb = sys.argv[1:]
    if verb == ["ensure"]:
        print(ensure())
    elif verb == ["show"] and key():
        print(key())
    elif verb == ["show"]:
        sys.exit(f"no gateway key: {HINT}")
    else:
        sys.exit("usage: python -m harness.gateway_key ensure|show")
