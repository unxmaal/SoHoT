"""Knobs of the demand census (#1151)."""
from harness.knobs.base import _k

_SRC = "evals/analysis/demand/__init__.py"

KNOBS = [
    _k("demand_days", [f"{_SRC}:DAYS"], [7, 14, 28],
       note="days of transcripts the census population reaches back from --now (#1151)"),
    _k("demand_floor", [f"{_SRC}:FLOOR"], [1, 2],
       note="draws every stratum gets before the rest go by output tokens (#1151)"),
    _k("demand_idle_gap", [f"{_SRC}:IDLE_GAP_S"], [120, 600, 1800],
       note="seconds between two records past which the gap counts as idle, not a subtask's wall time (#1151)"),
    _k("demand_request_cap", [f"{_SRC}:REQUEST_CAP"], [500, 1500, 4000],
       note="characters of a request a labeller's packet keeps (#1151)"),
    _k("demand_result_cap", [f"{_SRC}:RESULT_CAP"], [300, 600, 1500],
       note="characters of the final assistant text a labeller's packet keeps (#1151)"),
    _k("demand_step_cap", [f"{_SRC}:STEP_CAP"], [60, 100, 200],
       note="characters of one tool step a labeller's packet keeps (#1151)"),
    _k("demand_steps", [f"{_SRC}:STEPS"], [5, 15, 30],
       note="tool steps a labeller's packet lists (#1151)"),
]

NOT_GATING = {
    f"{_SRC}:public_repo->subprocess.run(timeout)": "how long gh may take to say a repo is public; a timeout "
                                                     "counts it private, so its name is masked (#1151)",
    f"{_SRC}:Unit.active_s": "a unit's measured wall time, summed from its records (#1151)",
    f"{_SRC}:Unit.tokens_in": "a unit's measured input tokens, summed from its messages (#1151)",
    f"{_SRC}:Unit.tokens_out": "a unit's measured output tokens, summed from its messages (#1151)",
}
