"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import parse_step

LIMIT = 81


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
