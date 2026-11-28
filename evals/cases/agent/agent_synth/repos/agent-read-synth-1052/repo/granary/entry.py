"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import allocate_step
from granary.stages import normalize_step
from granary.stages import estimate_step
from granary.stages import merge_step
from granary.stages import parse_step
from granary.stages import render_step

LIMIT = 40


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = normalize_step.apply(value)
    value = estimate_step.apply(value)
    value = merge_step.apply(value)
    value = parse_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 4
