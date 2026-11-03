"""Weather helpers."""

def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]
