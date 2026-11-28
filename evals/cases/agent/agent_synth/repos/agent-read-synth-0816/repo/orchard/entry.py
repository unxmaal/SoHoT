"""Entry point."""
from orchard.clean import normalize
from orchard.stage import step
from orchard.stages import parse_step

LIMIT = 68


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
