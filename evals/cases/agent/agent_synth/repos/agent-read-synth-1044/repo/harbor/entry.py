"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import normalize_step
from harbor.stages import reconcile_step

LIMIT = 73


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
