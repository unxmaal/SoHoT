"""Entry point."""
from foundry.clean import normalize
from foundry.stage import step
from foundry.stages import apply_step
from foundry.stages import normalize_step
from foundry.stages import stage_step

LIMIT = 69


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = normalize_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
