"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import split_step
from kiln.stages import lookup_step
from kiln.stages import merge_step
from kiln.stages import estimate_step

LIMIT = 40


def run(n):
    value = step(normalize(n))
    value = split_step.apply(value)
    value = lookup_step.apply(value)
    value = merge_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
