"""Entry point."""
from mill.clean import normalize
from mill.stage import step

LIMIT = 67


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
