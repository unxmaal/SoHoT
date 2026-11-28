"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step

LIMIT = 56


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
