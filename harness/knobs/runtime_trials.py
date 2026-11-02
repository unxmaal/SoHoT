"""Knobs of runtime upgrade trials (#1474)."""
from harness.knobs.base import _k

M = "harness/runtime_trials.py"

KNOBS = [
    _k("runtime_fetch_timeout_s", [f"{M}:FETCH_TIMEOUT_S"], [30.0, 60.0, 120.0],
       note="seconds reading a llama.cpp release's build-tag asset may take; past it the channel reads as unreachable this loop (#1474)"),
    _k("runtime_install_timeout_s", [f"{M}:INSTALL_TIMEOUT_S"], [600.0, 1800.0, 3600.0],
       note="seconds one sandboxed trial-install step (uv venv, uv pip install, a release download) may take (#1474)"),
    _k("runtime_smoke_timeout_s", [f"{M}:SMOKE_TIMEOUT_S"], [60.0, 120.0, 300.0],
       note="seconds a trial runtime's import or --version smoke run, or an unpack, may take (#1474)"),
    _k("runtime_trials_per_loop", [f"{M}:TRIALS_PER_LOOP"], [1, 2, 4],
       note="proposed runtime releases one discovery loop trial-installs; the rest wait for the next loop (#1474)"),
]
