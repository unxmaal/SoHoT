"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import reconcile_step
from wharf.stages import merge_step
from wharf.stages import rank_step

LIMIT = 66


def run(n):
    value = step(normalize(n))
    value = reconcile_step.apply(value)
    value = merge_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
