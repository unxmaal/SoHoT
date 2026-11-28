"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import merge_step
from wharf.stages import parse_step

LIMIT = 40


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
