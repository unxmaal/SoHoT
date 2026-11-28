"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import resolve_step
from wharf.stages import validate_step
from wharf.stages import load_step
from wharf.stages import stage_step
from wharf.stages import split_step
from wharf.stages import apply_step
from wharf.stages import merge_step

LIMIT = 45


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = validate_step.apply(value)
    value = load_step.apply(value)
    value = stage_step.apply(value)
    value = split_step.apply(value)
    value = apply_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
