"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import parse_step
from lantern.stages import merge_step
from lantern.stages import lookup_step

LIMIT = 41


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    value = merge_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
