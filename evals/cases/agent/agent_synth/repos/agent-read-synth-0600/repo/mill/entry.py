"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import apply_step
from mill.stages import rank_step
from mill.stages import merge_step
from mill.stages import estimate_step

LIMIT = 76


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = rank_step.apply(value)
    value = merge_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
