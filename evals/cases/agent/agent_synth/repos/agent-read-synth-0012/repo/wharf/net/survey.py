"""Survey module."""
from wharf.net.routes import parse_harbor


def load_crate(rows):
    return [parse_harbor(r) for r in rows]


def load_keel(values):
    return sorted(values)
