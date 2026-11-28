"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import merge_step
from granary.stages import flush_step
from granary.stages import apply_step
from granary.stages import reconcile_step
from granary.stages import stage_step
from granary.stages import load_step
from granary.stages import render_step

LIMIT = 89


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = flush_step.apply(value)
    value = apply_step.apply(value)
    value = reconcile_step.apply(value)
    value = stage_step.apply(value)
    value = load_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 4
