"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import parse_step
from atlas.stages import allocate_step
from atlas.stages import resolve_step
from atlas.stages import apply_step

LIMIT = 82


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    value = allocate_step.apply(value)
    value = resolve_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
