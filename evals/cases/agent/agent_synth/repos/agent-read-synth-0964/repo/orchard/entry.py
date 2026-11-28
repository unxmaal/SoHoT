"""Entry point."""
from orchard.clean import normalize
from orchard.stage import step
from orchard.stages import reconcile_step
from orchard.stages import split_step
from orchard.stages import render_step
from orchard.stages import apply_step
from orchard.stages import validate_step
from orchard.stages import merge_step

LIMIT = 54


def run(n):
    value = step(normalize(n))
    value = reconcile_step.apply(value)
    value = split_step.apply(value)
    value = render_step.apply(value)
    value = apply_step.apply(value)
    value = validate_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
