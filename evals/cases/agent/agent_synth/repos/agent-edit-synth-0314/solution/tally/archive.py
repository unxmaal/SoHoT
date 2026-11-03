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


def top_n(counts, n, min_count=0):
    """The n keys with the highest counts, ties in key order."""
    kept = [k for k in counts if counts[k] >= min_count]
    return sorted(kept, key=lambda k: (-counts[k], k))[:n]


def format_cents(cents):
    """Cents as dollars with thousands separators, such as -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
