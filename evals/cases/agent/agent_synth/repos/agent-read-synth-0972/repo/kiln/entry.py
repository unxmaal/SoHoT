"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import allocate_step
from kiln.stages import resolve_step

LIMIT = 55


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
