"""Entry point."""
from compass.clean import normalize
from compass.stage import step
from compass.stages import allocate_step
from compass.stages import split_step
from compass.stages import apply_step
from compass.stages import parse_step
from compass.stages import validate_step
from compass.stages import reconcile_step
from compass.stages import merge_step

LIMIT = 81


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = split_step.apply(value)
    value = apply_step.apply(value)
    value = parse_step.apply(value)
    value = validate_step.apply(value)
    value = reconcile_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
