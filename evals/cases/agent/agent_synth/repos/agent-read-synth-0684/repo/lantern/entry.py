"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import apply_step
from lantern.stages import reconcile_step
from lantern.stages import lookup_step

LIMIT = 81


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = reconcile_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
