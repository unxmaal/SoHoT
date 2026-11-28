"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import apply_step
from kiln.stages import merge_step
from kiln.stages import reconcile_step
from kiln.stages import flush_step

LIMIT = 41


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = merge_step.apply(value)
    value = reconcile_step.apply(value)
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
