"""Knobs of uv cache (#2049)."""

KNOBS = []

NOT_GATING = {
    "harness/uv_cache.py:PRUNE_TIMEOUT_S": "a cleanup that frees disk; when it binds the sweep reports the prune skipped and judges nothing (#2049)",
    "harness/uv_cache.py:DIR_TIMEOUT_S": "asking uv where its cache is; when it binds the prune is skipped and nothing is judged (#2049)",
}
