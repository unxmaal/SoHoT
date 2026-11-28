"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import merge_step
from kiln.stages import allocate_step
from kiln.stages import load_step

LIMIT = 85


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = allocate_step.apply(value)
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
