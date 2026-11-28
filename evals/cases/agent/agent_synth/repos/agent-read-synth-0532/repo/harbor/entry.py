"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import apply_step
from harbor.stages import load_step
from harbor.stages import resolve_step
from harbor.stages import render_step
from harbor.stages import estimate_step
from harbor.stages import rank_step
from harbor.stages import validate_step

LIMIT = 57


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = load_step.apply(value)
    value = resolve_step.apply(value)
    value = render_step.apply(value)
    value = estimate_step.apply(value)
    value = rank_step.apply(value)
    value = validate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
