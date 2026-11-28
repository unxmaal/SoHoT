"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import merge_step
from granary.stages import stage_step
from granary.stages import flush_step
from granary.stages import allocate_step

LIMIT = 72


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = stage_step.apply(value)
    value = flush_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
