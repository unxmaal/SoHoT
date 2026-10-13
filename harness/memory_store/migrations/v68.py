"""Schema 68: gateway_requests.purpose, from the caller's purpose:<x> tag. #825."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 68


def columns(conn) -> None:
    cols._add_request_purpose(conn)
