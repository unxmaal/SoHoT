"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import apply_step
from lantern.stages import rank_step
from lantern.stages import parse_step

LIMIT = 51


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = rank_step.apply(value)
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
