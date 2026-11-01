"""Knobs of the `soh unverified` Stop hook (#1380)."""
from harness.knobs.base import _k

U = "harness/unverified.py"

KNOBS = [
    _k("unverified_claims", [f"{U}:CLAIMS_PER_TURN"], [6, 12, 24], limit="unverified_claims", unit="calls",
       note="candidate claims one Stop hook sends to the decide model, one call each, about 0.2 s each once the "
            "model is resident (Studio 2026-10-30); the planted turns have 10-11; the rest go unchecked (#1380)"),
    _k("unverified_evidence_chars", [f"{U}:EVIDENCE_CHARS"], [1200, 2400, 4800], limit="unverified_evidence_chars",
       unit="chars", note="characters of the turn's tool output, the windows sharing the claim's rarest terms, put "
                          "before the decide model with one claim (#1380)"),
    _k("unverified_shown_p", [f"{U}:SHOWN_P"], [0.5, 0.8, 0.9, 0.95],
       note="decide-model probability of shown below which a factual claim is flagged; the adopted decide model "
            "was right on 0.92 of fields at confidence 0.9 and up against 0.71 below (FINDING #393); on the "
            "near-miss turn supported claims scored 0.971-0.997 and unsupported 0.211-0.756, so 0.5 flags 2 of 5 "
            "and 0.9 flags 5 of 5 with none of the supported (#1380)"),
    _k("unverified_transcript_bytes", [f"{U}:TRANSCRIPT_BYTES"], [1024 ** 2, 4 * 1024 ** 2, 16 * 1024 ** 2],
       limit="unverified_transcript_bytes", unit="bytes",
       note="bytes of the transcript's tail the hook reads; a turn starting before them is allowed unchecked; a "
            "coordinator transcript reached 205 MB on 2026-10-30, so the whole file is never read (#1380)"),
    _k("unverified_turn_timeout_s", [f"{U}:TURN_TIMEOUT_S"], [5.0, 10.0, 30.0], limit="unverified_turn_timeout_s",
       unit="s", note="seconds one Stop hook check may take before it allows the stop unchecked; the issue's bar "
                      "is under 10 s per turn. Measured on the Studio 2026-10-30, imajev-4b-Q8_0 resident, 10-11 "
                      "claims: check 2.8-7.1 s, whole hook process 5.5-7.7 s, of which the first decide call's "
                      "machine probe is 3.4 s and each later call 0.2 s; with the model unloaded the deadline "
                      "allowed the stop (#1380)"),
]

NOT_GATING = {
    f"{U}:WINDOW_CHARS": "size of one evidence window the retrieval ranks; EVIDENCE_CHARS bounds what is sent (#1380)",
    f"{U}:SESSIONS_KEPT": "sessions the blocked-turn state file remembers; an older session has no live turn (#1380)",
}
