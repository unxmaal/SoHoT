"""Knobs of uv cache (#2049)."""
from harness.knobs.base import _k

KNOBS = [
    _k("uv_env_max_age", ["harness/uv_cache.py:ENV_MAX_AGE_S"], [86400, 172800, 604800], unit="s",
       note="seconds an unused cached uv environment stays before the disk sweep removes it (#2050)"),
]

NOT_GATING = {
    "harness/uv_cache.py:PRUNE_TIMEOUT_S": "a cleanup that frees disk; when it binds the sweep reports the prune skipped and judges nothing (#2049)",
    "harness/uv_cache.py:DIR_TIMEOUT_S": "asking uv where its cache is; when it binds the prune is skipped and nothing is judged (#2049)",
    "harness/uv_cache.py:LSOF_TIMEOUT_S": "listing open files to find the cached environments in use; when it binds no environment is removed and nothing is judged (#2050)",
}
