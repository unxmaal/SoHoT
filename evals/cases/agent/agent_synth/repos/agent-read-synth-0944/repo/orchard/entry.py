"""Entry point."""
from orchard.clean import normalize
from orchard.stage import step
from orchard.stages import lookup_step
from orchard.stages import allocate_step
from orchard.stages import parse_step
from orchard.stages import load_step
from orchard.stages import flush_step

LIMIT = 81


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = allocate_step.apply(value)
    value = parse_step.apply(value)
    value = load_step.apply(value)
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
