"""`soh gateway`: the gateway's key. #482."""
from __future__ import annotations

import sys

from harness.commands.common import say


def cmd_gateway(a) -> int:
    """`soh gateway key`: this machine's gateway key, created on first ask. #482."""
    from harness import gateway_key
    if a.rotate:
        k = gateway_key.rotate()
        print("rotated; restart the gateway to use it, and update every "
              "client that has the old one", file=sys.stderr)
    else:
        k = gateway_key.ensure()
    return say(body=k, human=k)
