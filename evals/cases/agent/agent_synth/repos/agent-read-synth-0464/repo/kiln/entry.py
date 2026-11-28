"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import rank_step
from kiln.stages import render_step
from kiln.stages import apply_step
from kiln.stages import flush_step

LIMIT = 56


def run(n):
    value = step(normalize(n))
    value = rank_step.apply(value)
    value = render_step.apply(value)
    value = apply_step.apply(value)
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
