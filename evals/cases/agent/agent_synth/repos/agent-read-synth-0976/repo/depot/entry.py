"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import rank_step
from depot.stages import normalize_step
from depot.stages import apply_step
from depot.stages import resolve_step

LIMIT = 40


def run(n):
    value = step(normalize(n))
    value = rank_step.apply(value)
    value = normalize_step.apply(value)
    value = apply_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
