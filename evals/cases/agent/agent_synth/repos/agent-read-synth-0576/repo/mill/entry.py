"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import normalize_step
from mill.stages import apply_step
from mill.stages import load_step
from mill.stages import lookup_step

LIMIT = 54


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = apply_step.apply(value)
    value = load_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
