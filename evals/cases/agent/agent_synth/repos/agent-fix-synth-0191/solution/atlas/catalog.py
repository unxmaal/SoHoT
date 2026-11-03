"""Catalog helpers."""

def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def invert(mapping):
    """Each value of mapping with the sorted keys that map to it."""
    out = {}
    for key, value in mapping.items():
        out.setdefault(value, []).append(key)
    return {value: sorted(keys) for value, keys in out.items()}
