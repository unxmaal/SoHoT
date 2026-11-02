"""Knobs of the engine trials the discovery loop runs on engines and runners wanted (#1475)."""
from harness.knobs.base import _k

M = "harness/engine_trials.py"

KNOBS = [
    _k("engine_classify_per_run", [f"{M}:PER_RUN"], [0, 2, 6, 20],
       note="tooling repos one sweep has the extract lane's model classify; 12 recurred on the night #1475 was filed (#1475)"),
    _k("engine_classify_tokens", [f"{M}:CLASSIFY_TOKENS"], [600, 1200, 2400],
       note="reply budget of one classification, a JSON object of five fields (#1475)"),
    _k("engine_install_timeout_s", [f"{M}:INSTALL_TIMEOUT_S"], [300.0, 900.0, 1800.0],
       note="seconds one sandboxed uv venv or uv pip install of a trial engine may take before the trial is blocked (#1475)"),
    _k("engine_installs_per_run", [f"{M}:INSTALLS_PER_RUN"], [0, 1, 2, 5],
       note="trial installs one sweep makes; each spends disk and minutes (#1475)"),
    _k("engine_screens_per_run", [f"{M}:SCREENS_PER_RUN"], [0, 2, 4, 10],
       note="runner-wanted candidates one sweep screens on trial engines; each loads a model (#1475)"),
    _k("engine_serve_timeout_s", [f"{M}:SERVE_TIMEOUT_S"], [120.0, 600.0, 1200.0],
       note="seconds a trial engine may take to answer /v1/models before its screen is load_failed (#1475)"),
]

NOT_GATING = {
    f"{M}:GH_TIMEOUT_S": "how long gh or a PyPI read may take; a timeout reads as no evidence or no issue this sweep (#1475)",
    f"{M}:README_CHARS": "characters of a README the classifier reads; presentation of evidence, not a verdict (#1475)",
}
