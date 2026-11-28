"""Entry point."""
from foundry.clean import normalize
from foundry.stage import step

LIMIT = 87


def run(n):
    value = step(normalize(n))
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
