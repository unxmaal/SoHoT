"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step

LIMIT = 53


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
