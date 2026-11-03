"""Archive helpers."""
from granary.ledger import snake_case


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def dock_row(name):
    """One dock row for the archive page."""
    return {'dock_row': snake_case(name)}
