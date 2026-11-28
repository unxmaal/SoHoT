"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import rank_step
from atlas.stages import split_step
from atlas.stages import allocate_step
from atlas.stages import estimate_step
from atlas.stages import merge_step

LIMIT = 71


def run(n):
    value = step(normalize(n))
    value = rank_step.apply(value)
    value = split_step.apply(value)
    value = allocate_step.apply(value)
    value = estimate_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
