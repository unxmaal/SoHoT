"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import allocate_step
from kiln.stages import split_step
from kiln.stages import stage_step

LIMIT = 79


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = split_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
