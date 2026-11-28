"""Entry point."""
from foundry.clean import normalize
from foundry.stage import step
from foundry.stages import normalize_step
from foundry.stages import allocate_step
from foundry.stages import render_step
from foundry.stages import flush_step
from foundry.stages import apply_step

LIMIT = 53


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = allocate_step.apply(value)
    value = render_step.apply(value)
    value = flush_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
