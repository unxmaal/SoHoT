"""Entry point."""
from quarry.clean import normalize
from quarry.stage import step
from quarry.stages import resolve_step
from quarry.stages import normalize_step

LIMIT = 67


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
