"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import flush_step
from mill.stages import stage_step
from mill.stages import allocate_step

LIMIT = 55


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    value = stage_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
