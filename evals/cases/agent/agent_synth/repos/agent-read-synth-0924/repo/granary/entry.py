"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import stage_step
from granary.stages import parse_step
from granary.stages import lookup_step
from granary.stages import validate_step

LIMIT = 51


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = parse_step.apply(value)
    value = lookup_step.apply(value)
    value = validate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
