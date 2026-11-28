"""Entry point."""
from orchard.clean import normalize
from orchard.stage import step
from orchard.stages import reconcile_step
from orchard.stages import normalize_step

LIMIT = 67


def run(n):
    value = step(normalize(n))
    value = reconcile_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
