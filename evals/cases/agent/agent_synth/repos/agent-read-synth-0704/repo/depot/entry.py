"""Entry point."""
from depot.clean import normalize
from depot.stage import step

LIMIT = 70


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
