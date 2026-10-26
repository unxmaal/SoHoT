"""Knobs of how a pass threshold is derived from a known-good instrument's noise floor (#730)."""
from harness.knobs.base import _k

KNOBS = [
    _k("floor_gap_window", ["harness/floors.py:FLOOR_GAP_WINDOW"], [1.25, 1.5, 2.0], unit="factor",
       note="factor either side of a session gap whose observed gaps score it; the sparsest value is derived (#730)"),
    _k("floor_min_items", ["harness/floors.py:FLOOR_MIN_ITEMS"], [5, 10, 20], unit="cases",
       note="distinct items a length stratum needs to set a floor alone; a smaller one pools with its neighbour (#730)"),
    _k("floor_pass_share", ["harness/floors.py:FLOOR_PASS_SHARE"], [0.9, 0.95, 0.99], unit="share",
       note="share of clean items a known-good instrument must pass in every length stratum at a derived threshold (#730)"),
]

NOT_GATING = {
    **{f"harness/floors.py:STRATA[{lane}]": "item-length bounds `soh floors` reports each lane's floor by; a "
                                             "stratum under floor_min_items sets nothing (#730)"
       for lane in ("ocr", "stt", "tts")},
}

NEVER_CUTS = {
    "harness/floors.py:FLOOR_GAP_WINDOW": "how a session gap is scored; it drops no row (#730)",
    "harness/floors.py:FLOOR_MIN_ITEMS": "which strata may set a floor; every row is reported (#730)",
    "harness/floors.py:FLOOR_PASS_SHARE": "the quantile a floor is read at; every row is reported (#730)",
}
