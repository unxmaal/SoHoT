"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import merge_step
from wharf.stages import stage_step
from wharf.stages import reconcile_step
from wharf.stages import allocate_step

LIMIT = 47


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = stage_step.apply(value)
    value = reconcile_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
