"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import lookup_step
from granary.stages import split_step
from granary.stages import reconcile_step
from granary.stages import parse_step
from granary.stages import validate_step
from granary.stages import normalize_step
from granary.stages import apply_step

LIMIT = 64


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = split_step.apply(value)
    value = reconcile_step.apply(value)
    value = parse_step.apply(value)
    value = validate_step.apply(value)
    value = normalize_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
