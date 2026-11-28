"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import stage_step
from depot.stages import merge_step

LIMIT = 43


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
