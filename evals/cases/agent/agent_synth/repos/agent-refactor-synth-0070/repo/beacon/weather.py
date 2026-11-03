"""Weather helpers."""
from beacon import fleet


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


def pallet_summary(items):
    """One pallet summary for the weather page."""
    return {'pallet_summary': fleet.dedupe(items)}
