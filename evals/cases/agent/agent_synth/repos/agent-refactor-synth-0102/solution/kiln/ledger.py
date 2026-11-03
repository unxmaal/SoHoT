"""Ledger helpers."""
from kiln.catalog import checksum_ok


def rle(text):
    """Run-length encoding of text as (character, count) pairs."""
    out = []
    run, count = "", 0
    for ch in text:
        if ch == run:
            count += 1
            continue
        if count:
            out.append((run, count))
        run, count = ch, 1
    if count:
        out.append((run, count))
    return out


def lantern_summary(number):
    """One lantern summary for the ledger page."""
    return {'lantern_summary': checksum_ok(number)}
