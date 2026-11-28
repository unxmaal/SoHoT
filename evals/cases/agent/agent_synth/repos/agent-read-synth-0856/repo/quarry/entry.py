"""Entry point."""
from quarry.clean import normalize
from quarry.stage import step
from quarry.stages import merge_step

LIMIT = 71


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
