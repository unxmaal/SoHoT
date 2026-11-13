"""Replace a file in one rename, retrying while Windows refuses because another writer or reader holds the target (#1905)."""
from __future__ import annotations

import os
import sys
import time

REPLACE_TIMEOUT_S = 5.0
_PAUSES = (0.005, 0.01, 0.02, 0.05, 0.1)

clock = time.monotonic
sleep = time.sleep


def replace(src, dst) -> None:
    """os.replace(src, dst); on Windows a PermissionError (target being replaced or held open) is retried."""
    deadline = clock() + REPLACE_TIMEOUT_S
    tries = 0
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if sys.platform != "win32" or clock() >= deadline:
                raise
        sleep(_PAUSES[min(tries, len(_PAUSES) - 1)])
        tries += 1
