"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import lookup_step
from depot.stages import validate_step
from depot.stages import allocate_step
from depot.stages import merge_step
from depot.stages import parse_step

LIMIT = 42


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = validate_step.apply(value)
    value = allocate_step.apply(value)
    value = merge_step.apply(value)
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
