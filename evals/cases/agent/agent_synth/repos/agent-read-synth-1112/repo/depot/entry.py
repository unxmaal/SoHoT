"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import allocate_step
from depot.stages import reconcile_step
from depot.stages import split_step
from depot.stages import lookup_step
from depot.stages import parse_step

LIMIT = 84


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = reconcile_step.apply(value)
    value = split_step.apply(value)
    value = lookup_step.apply(value)
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
