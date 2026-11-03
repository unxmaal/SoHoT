"""Weather helpers."""

def paginate(items, page, per_page):
    """The items on a 1-based page of per_page items."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page start at 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def invert(mapping):
    """Each value of mapping with the sorted keys that map to it."""
    out = {}
    for key, value in mapping.items():
        out.setdefault(value, []).append(key)
    return {value: sorted(keys) for value, keys in out.items()}
