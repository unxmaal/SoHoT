"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import resolve_step
from depot.stages import reconcile_step
from depot.stages import flush_step
from depot.stages import lookup_step
from depot.stages import apply_step

LIMIT = 89


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = reconcile_step.apply(value)
    value = flush_step.apply(value)
    value = lookup_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
