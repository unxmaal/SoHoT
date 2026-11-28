"""Entry point."""
from orchard.clean import normalize
from orchard.stage import step
from orchard.stages import resolve_step
from orchard.stages import stage_step
from orchard.stages import split_step
from orchard.stages import lookup_step
from orchard.stages import validate_step
from orchard.stages import apply_step

LIMIT = 62


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = stage_step.apply(value)
    value = split_step.apply(value)
    value = lookup_step.apply(value)
    value = validate_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
