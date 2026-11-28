"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import render_step
from lantern.stages import load_step
from lantern.stages import resolve_step
from lantern.stages import allocate_step
from lantern.stages import lookup_step
from lantern.stages import flush_step
from lantern.stages import split_step

LIMIT = 63


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    value = load_step.apply(value)
    value = resolve_step.apply(value)
    value = allocate_step.apply(value)
    value = lookup_step.apply(value)
    value = flush_step.apply(value)
    value = split_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
