"""Entry point."""
from depot.clean import normalize
from depot.stage import step

LIMIT = 60


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
