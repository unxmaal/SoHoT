"""Entry point."""
from quarry.clean import normalize
from quarry.stage import step
from quarry.stages import split_step
from quarry.stages import resolve_step
from quarry.stages import merge_step
from quarry.stages import apply_step
from quarry.stages import estimate_step
from quarry.stages import allocate_step

LIMIT = 84


def run(n):
    value = step(normalize(n))
    value = split_step.apply(value)
    value = resolve_step.apply(value)
    value = merge_step.apply(value)
    value = apply_step.apply(value)
    value = estimate_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 4
