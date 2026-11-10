"""Knobs of `soh digest`: the checked log digest and its A/B (#1690)."""
from harness.knobs.base import _k

KNOBS = [
    _k("digest_check_items", ["harness/digest.py:CHECK_ITEMS"], [20, 60, 200],
       note="lines the check adds to one digest before it names the rest by count (#1690)"),
    _k("digest_key_chars", ["harness/digest.py:KEY_CHARS"], [40, 80, 160],
       note="characters of an exception line that must reappear for the digest to have kept it (#1690)"),
]

NOT_GATING = {
    "evals/digest_ab.py:gh_log->subprocess.run(timeout)": "how long gh may take to fetch one failed run's log while "
                                                          "the recorded set is rebuilt by hand; the A/B never fetches (#1690)",
}
