"""Entry point."""
from tally.clean import normalize
from tally.stage import step

LIMIT = 67


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
