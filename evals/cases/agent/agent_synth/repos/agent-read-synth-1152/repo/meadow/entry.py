"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import estimate_step
from meadow.stages import allocate_step
from meadow.stages import lookup_step

LIMIT = 71


def run(n):
    value = step(normalize(n))
    value = estimate_step.apply(value)
    value = allocate_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
