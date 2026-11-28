"""Entry point."""
from quarry.clean import normalize
from quarry.stage import step
from quarry.stages import allocate_step
from quarry.stages import estimate_step
from quarry.stages import split_step
from quarry.stages import stage_step
from quarry.stages import flush_step
from quarry.stages import parse_step
from quarry.stages import resolve_step

LIMIT = 72


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = estimate_step.apply(value)
    value = split_step.apply(value)
    value = stage_step.apply(value)
    value = flush_step.apply(value)
    value = parse_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
