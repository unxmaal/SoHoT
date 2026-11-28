"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import stage_step
from atlas.stages import rank_step
from atlas.stages import estimate_step

LIMIT = 44


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = rank_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
