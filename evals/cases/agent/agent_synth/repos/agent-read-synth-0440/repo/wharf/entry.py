"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import apply_step
from wharf.stages import parse_step
from wharf.stages import rank_step
from wharf.stages import reconcile_step
from wharf.stages import flush_step
from wharf.stages import split_step
from wharf.stages import render_step

LIMIT = 67


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = parse_step.apply(value)
    value = rank_step.apply(value)
    value = reconcile_step.apply(value)
    value = flush_step.apply(value)
    value = split_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
