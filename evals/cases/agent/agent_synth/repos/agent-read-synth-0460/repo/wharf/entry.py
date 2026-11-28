"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import resolve_step
from wharf.stages import normalize_step
from wharf.stages import estimate_step

LIMIT = 47


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = normalize_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
