"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import estimate_step
from depot.stages import normalize_step
from depot.stages import allocate_step
from depot.stages import render_step
from depot.stages import stage_step
from depot.stages import apply_step
from depot.stages import rank_step

LIMIT = 54


def run(n):
    value = step(normalize(n))
    value = estimate_step.apply(value)
    value = normalize_step.apply(value)
    value = allocate_step.apply(value)
    value = render_step.apply(value)
    value = stage_step.apply(value)
    value = apply_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
