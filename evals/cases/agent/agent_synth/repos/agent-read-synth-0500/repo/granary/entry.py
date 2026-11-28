"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import allocate_step

LIMIT = 80


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
