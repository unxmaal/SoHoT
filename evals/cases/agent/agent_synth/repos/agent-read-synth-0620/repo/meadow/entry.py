"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import allocate_step
from meadow.stages import estimate_step

LIMIT = 89


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
