"""Ledger helpers."""
from mill import routes


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def hull_check(number):
    """One hull check for the ledger page."""
    return {'hull_check': routes.checksum_ok(number)}
