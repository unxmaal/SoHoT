"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import stage_step
from harbor.stages import split_step
from harbor.stages import load_step
from harbor.stages import render_step
from harbor.stages import merge_step
from harbor.stages import allocate_step
from harbor.stages import estimate_step

LIMIT = 89


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = split_step.apply(value)
    value = load_step.apply(value)
    value = render_step.apply(value)
    value = merge_step.apply(value)
    value = allocate_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
