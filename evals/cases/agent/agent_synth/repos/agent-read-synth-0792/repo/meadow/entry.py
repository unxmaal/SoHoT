"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step

LIMIT = 60


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
