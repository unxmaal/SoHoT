"""Schema 31: weights on disk are downloads rows, backfilled before the older steps read them. #411."""
from __future__ import annotations

VERSION = 31


def early(conn) -> None:
    # Before the older steps, so have() reads rows, not the hub. #411.
    from harness import downloads
    downloads.backfill(conn)
