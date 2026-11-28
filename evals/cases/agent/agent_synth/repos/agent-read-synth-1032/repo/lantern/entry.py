"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import lookup_step
from lantern.stages import estimate_step
from lantern.stages import parse_step
from lantern.stages import reconcile_step

LIMIT = 48


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = estimate_step.apply(value)
    value = parse_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 4
