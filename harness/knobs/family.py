"""Knobs of the family term in the queue and the measure step's diversity slot (#1100, #1111)."""
from harness.knobs.base import _k

F = "harness/family.py"

KNOBS = [
    _k("diversity_family_window_days", [f"{F}:WINDOW_DAYS"], [7.0, 14.0, 30.0, 60.0],
       note="days a lane's paired comparison of a family counts as recent; 2026-10-22 store: code comparisons span "
            "09-22..10-22, at 14 the slot went to Qwen3-8B-4bit (qwen3-8b, 2 lost, 16 days ago), at 30 to "
            "Qwopus3.6-27B (qwen3.6-27b, never compared) (#1111)"),
    _k("diversity_slots", [f"{F}:SLOTS"], [0, 1, 2],
       note="measure slots a sweep holds for a family with no recent paired comparison in its lane; about 4 "
            "measurements a night (median, 7 nights to 2026-10-22), so 1 is a quarter of the night (#1111)"),
    _k("family_demotion", [f"{F}:DEMOTION"], [-1.5, -3.0, -4.5],
       note="rank.value a demoted family's other members lose; 2026-10-22 code queue head 30 spans +7.85..+5.85: the "
            "head sibling (Swift-Qwen3.8-27b-GGUF) drops to #21 at -1.5, #60 at -3.0, #94 at -4.5 (#1100)"),
    _k("family_hops", [f"{F}:HOPS"], [4, 8, 16],
       note="lineage hops followed to a root; a cycle or a longer chain stops there (#1100)"),
    _k("family_losses_to_demote", [f"{F}:LOSSES_TO_DEMOTE"], [2, 3, 5],
       note="distinct members of a lineage root lost at the paired gate in a lane since its last win before the "
            "rest rank lower; 2026-10-22 store: 29 of 31 code comparisons of models lost, roots with 2 losers are "
            "qwen3.8-27b, qwen3-8b, lfm2.5-350m and only the incumbent's own has 3 (#1100)"),
    _k("family_size_ratio", [f"{F}:SIZE_RATIO"], [1.5, 2.0, 4.0],
       note="a lineage parent this many times larger or smaller than its child ends the chain to the root; of 293 "
            "lineage edges 6 change size by up to 2x (VL towers, merges), Holo-3.1-35B-A3B -> Qwen3.5-0.8B by 44x (#1100)"),
]

NOT_GATING = {
    "harness/commands/families.py:DAY": "seconds in a day (#1100)",
}

NEVER_CUTS = {
    "harness/family.py:DEMOTION": "a rank offset; the demoted row stays in the queue at a lower place (#1087)",
}
