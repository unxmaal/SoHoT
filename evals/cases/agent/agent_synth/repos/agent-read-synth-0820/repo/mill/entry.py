"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import lookup_step
from mill.stages import reconcile_step
from mill.stages import allocate_step

LIMIT = 86


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = reconcile_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
