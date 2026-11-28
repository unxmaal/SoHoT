"""Entry point."""
from orchard.clean import normalize
from orchard.stage import step
from orchard.stages import allocate_step
from orchard.stages import split_step

LIMIT = 43


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = split_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
