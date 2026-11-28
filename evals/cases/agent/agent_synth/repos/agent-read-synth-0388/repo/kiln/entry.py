"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import normalize_step
from kiln.stages import apply_step
from kiln.stages import render_step
from kiln.stages import rank_step
from kiln.stages import estimate_step
from kiln.stages import merge_step
from kiln.stages import resolve_step

LIMIT = 65


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = apply_step.apply(value)
    value = render_step.apply(value)
    value = rank_step.apply(value)
    value = estimate_step.apply(value)
    value = merge_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
