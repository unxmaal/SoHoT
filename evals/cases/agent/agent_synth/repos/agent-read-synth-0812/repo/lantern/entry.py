"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import merge_step
from lantern.stages import rank_step
from lantern.stages import validate_step
from lantern.stages import estimate_step
from lantern.stages import resolve_step
from lantern.stages import render_step
from lantern.stages import flush_step

LIMIT = 55


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = rank_step.apply(value)
    value = validate_step.apply(value)
    value = estimate_step.apply(value)
    value = resolve_step.apply(value)
    value = render_step.apply(value)
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
