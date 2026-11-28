"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import apply_step
from harbor.stages import load_step
from harbor.stages import reconcile_step
from harbor.stages import rank_step
from harbor.stages import normalize_step
from harbor.stages import resolve_step

LIMIT = 86


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = load_step.apply(value)
    value = reconcile_step.apply(value)
    value = rank_step.apply(value)
    value = normalize_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
