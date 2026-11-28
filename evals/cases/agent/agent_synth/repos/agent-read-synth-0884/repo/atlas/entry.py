"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import allocate_step
from atlas.stages import estimate_step
from atlas.stages import reconcile_step
from atlas.stages import rank_step
from atlas.stages import lookup_step

LIMIT = 70


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = estimate_step.apply(value)
    value = reconcile_step.apply(value)
    value = rank_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
