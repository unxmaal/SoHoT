"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import stage_step
from depot.stages import merge_step
from depot.stages import lookup_step
from depot.stages import estimate_step
from depot.stages import flush_step

LIMIT = 68


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = merge_step.apply(value)
    value = lookup_step.apply(value)
    value = estimate_step.apply(value)
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
