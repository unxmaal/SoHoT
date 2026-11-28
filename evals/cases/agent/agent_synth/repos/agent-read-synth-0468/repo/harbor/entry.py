"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import validate_step
from harbor.stages import parse_step
from harbor.stages import rank_step
from harbor.stages import estimate_step
from harbor.stages import allocate_step
from harbor.stages import render_step

LIMIT = 55


def run(n):
    value = step(normalize(n))
    value = validate_step.apply(value)
    value = parse_step.apply(value)
    value = rank_step.apply(value)
    value = estimate_step.apply(value)
    value = allocate_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
