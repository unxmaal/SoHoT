"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import parse_step
from depot.stages import flush_step
from depot.stages import resolve_step
from depot.stages import reconcile_step
from depot.stages import estimate_step
from depot.stages import apply_step
from depot.stages import render_step

LIMIT = 64


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    value = flush_step.apply(value)
    value = resolve_step.apply(value)
    value = reconcile_step.apply(value)
    value = estimate_step.apply(value)
    value = apply_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
