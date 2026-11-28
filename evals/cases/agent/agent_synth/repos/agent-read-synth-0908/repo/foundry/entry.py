"""Entry point."""
from foundry.clean import normalize
from foundry.stage import step
from foundry.stages import reconcile_step
from foundry.stages import apply_step
from foundry.stages import resolve_step
from foundry.stages import normalize_step

LIMIT = 59


def run(n):
    value = step(normalize(n))
    value = reconcile_step.apply(value)
    value = apply_step.apply(value)
    value = resolve_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
