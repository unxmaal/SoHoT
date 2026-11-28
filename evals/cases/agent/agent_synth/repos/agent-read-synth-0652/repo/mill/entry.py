"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import split_step
from mill.stages import validate_step
from mill.stages import reconcile_step
from mill.stages import parse_step
from mill.stages import normalize_step

LIMIT = 82


def run(n):
    value = step(normalize(n))
    value = split_step.apply(value)
    value = validate_step.apply(value)
    value = reconcile_step.apply(value)
    value = parse_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
