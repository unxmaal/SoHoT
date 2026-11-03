"""Catalog helpers."""
import re
from atlas import archive


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def tide_figure(text):
    """One tide figure for the catalog page."""
    return {'tide_figure': archive.parse_duration(text)}
