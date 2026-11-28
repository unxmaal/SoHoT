"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import resolve_step
from kiln.stages import load_step
from kiln.stages import rank_step
from kiln.stages import flush_step
from kiln.stages import reconcile_step

LIMIT = 50


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = load_step.apply(value)
    value = rank_step.apply(value)
    value = flush_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
