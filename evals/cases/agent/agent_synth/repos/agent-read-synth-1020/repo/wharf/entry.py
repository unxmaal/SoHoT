"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step

LIMIT = 43


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 4
