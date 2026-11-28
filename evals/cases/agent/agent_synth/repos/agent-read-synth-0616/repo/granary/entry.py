"""Entry point."""
from granary.clean import normalize
from granary.stage import step

LIMIT = 70


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
