"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import flush_step
from granary.stages import resolve_step
from granary.stages import apply_step
from granary.stages import reconcile_step

LIMIT = 57


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    value = resolve_step.apply(value)
    value = apply_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 4
