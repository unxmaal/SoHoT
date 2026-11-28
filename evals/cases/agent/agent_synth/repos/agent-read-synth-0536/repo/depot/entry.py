"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import stage_step
from depot.stages import estimate_step
from depot.stages import parse_step

LIMIT = 75


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = estimate_step.apply(value)
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
