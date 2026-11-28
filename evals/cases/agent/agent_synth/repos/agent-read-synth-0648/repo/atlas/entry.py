"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import normalize_step
from atlas.stages import allocate_step
from atlas.stages import merge_step

LIMIT = 46


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = allocate_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
