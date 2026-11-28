"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import normalize_step
from atlas.stages import load_step
from atlas.stages import resolve_step
from atlas.stages import parse_step
from atlas.stages import merge_step
from atlas.stages import stage_step

LIMIT = 41


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = load_step.apply(value)
    value = resolve_step.apply(value)
    value = parse_step.apply(value)
    value = merge_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
