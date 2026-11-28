"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import load_step

LIMIT = 59


def run(n):
    value = step(normalize(n))
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
