"""Entry point."""
from compass.clean import normalize
from compass.stage import step
from compass.stages import allocate_step
from compass.stages import load_step
from compass.stages import reconcile_step
from compass.stages import lookup_step

LIMIT = 76


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = load_step.apply(value)
    value = reconcile_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
