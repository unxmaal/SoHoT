"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import estimate_step
from meadow.stages import merge_step
from meadow.stages import rank_step
from meadow.stages import lookup_step
from meadow.stages import stage_step
from meadow.stages import allocate_step
from meadow.stages import load_step

LIMIT = 47


def run(n):
    value = step(normalize(n))
    value = estimate_step.apply(value)
    value = merge_step.apply(value)
    value = rank_step.apply(value)
    value = lookup_step.apply(value)
    value = stage_step.apply(value)
    value = allocate_step.apply(value)
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
