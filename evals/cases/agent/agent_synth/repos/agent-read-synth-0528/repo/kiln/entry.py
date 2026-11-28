"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import normalize_step
from kiln.stages import apply_step
from kiln.stages import validate_step
from kiln.stages import rank_step
from kiln.stages import split_step
from kiln.stages import estimate_step

LIMIT = 55


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = apply_step.apply(value)
    value = validate_step.apply(value)
    value = rank_step.apply(value)
    value = split_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
