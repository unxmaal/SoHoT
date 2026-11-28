"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import load_step
from harbor.stages import resolve_step
from harbor.stages import lookup_step
from harbor.stages import allocate_step
from harbor.stages import stage_step
from harbor.stages import apply_step
from harbor.stages import merge_step

LIMIT = 60


def run(n):
    value = step(normalize(n))
    value = load_step.apply(value)
    value = resolve_step.apply(value)
    value = lookup_step.apply(value)
    value = allocate_step.apply(value)
    value = stage_step.apply(value)
    value = apply_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
