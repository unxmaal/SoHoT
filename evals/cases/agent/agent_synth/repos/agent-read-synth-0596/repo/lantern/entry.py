"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import load_step
from lantern.stages import resolve_step
from lantern.stages import rank_step
from lantern.stages import normalize_step
from lantern.stages import stage_step
from lantern.stages import parse_step
from lantern.stages import allocate_step

LIMIT = 76


def run(n):
    value = step(normalize(n))
    value = load_step.apply(value)
    value = resolve_step.apply(value)
    value = rank_step.apply(value)
    value = normalize_step.apply(value)
    value = stage_step.apply(value)
    value = parse_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
