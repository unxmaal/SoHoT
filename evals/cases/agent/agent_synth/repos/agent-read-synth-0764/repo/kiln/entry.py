"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import split_step
from kiln.stages import allocate_step
from kiln.stages import resolve_step
from kiln.stages import normalize_step
from kiln.stages import merge_step

LIMIT = 46


def run(n):
    value = step(normalize(n))
    value = split_step.apply(value)
    value = allocate_step.apply(value)
    value = resolve_step.apply(value)
    value = normalize_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
