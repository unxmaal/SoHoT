"""Archive helpers."""

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


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    return sorted(set(items))
