"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import render_step
from wharf.stages import parse_step
from wharf.stages import estimate_step
from wharf.stages import apply_step
from wharf.stages import normalize_step
from wharf.stages import rank_step

LIMIT = 84


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    value = parse_step.apply(value)
    value = estimate_step.apply(value)
    value = apply_step.apply(value)
    value = normalize_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
