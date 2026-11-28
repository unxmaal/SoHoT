"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import merge_step
from mill.stages import allocate_step

LIMIT = 64


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
