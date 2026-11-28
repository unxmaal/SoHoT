"""Entry point."""
from compass.clean import normalize
from compass.stage import step

LIMIT = 61


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
