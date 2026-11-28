"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import lookup_step
from wharf.stages import load_step
from wharf.stages import rank_step
from wharf.stages import parse_step
from wharf.stages import validate_step
from wharf.stages import apply_step
from wharf.stages import allocate_step

LIMIT = 54


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = load_step.apply(value)
    value = rank_step.apply(value)
    value = parse_step.apply(value)
    value = validate_step.apply(value)
    value = apply_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
