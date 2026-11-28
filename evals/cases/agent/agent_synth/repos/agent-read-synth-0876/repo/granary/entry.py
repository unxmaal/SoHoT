"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import stage_step
from granary.stages import rank_step
from granary.stages import estimate_step
from granary.stages import parse_step
from granary.stages import allocate_step
from granary.stages import resolve_step

LIMIT = 41


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = rank_step.apply(value)
    value = estimate_step.apply(value)
    value = parse_step.apply(value)
    value = allocate_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
