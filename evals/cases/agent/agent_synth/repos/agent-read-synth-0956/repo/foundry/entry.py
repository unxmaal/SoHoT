"""Entry point."""
from foundry.clean import normalize
from foundry.stage import step
from foundry.stages import allocate_step
from foundry.stages import rank_step
from foundry.stages import stage_step

LIMIT = 89


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = rank_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
