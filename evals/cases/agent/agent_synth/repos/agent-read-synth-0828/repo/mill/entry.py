"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import apply_step
from mill.stages import normalize_step

LIMIT = 89


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
