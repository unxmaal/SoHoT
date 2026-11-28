"""Entry point."""
from orchard.clean import normalize
from orchard.stage import step
from orchard.stages import merge_step
from orchard.stages import stage_step
from orchard.stages import allocate_step
from orchard.stages import resolve_step

LIMIT = 69


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = stage_step.apply(value)
    value = allocate_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
