"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step

LIMIT = 59


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
