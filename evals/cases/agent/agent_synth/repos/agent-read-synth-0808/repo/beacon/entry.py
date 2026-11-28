"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step

LIMIT = 55


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
