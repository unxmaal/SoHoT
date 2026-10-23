"""Knobs of the demand census (#1151) and its shadow replay (#1161)."""
from harness.knobs.base import _k

_SRC = "evals/analysis/demand/__init__.py"
_REPLAY = "evals/analysis/demand/replay.py"

KNOBS = [
    _k("demand_cost_slack", [f"{_SRC}:COST_SLACK_S"], [0, 5, 60],
       note="seconds past a cost-state record's span a message may start and still be checked against it (#1151)"),
    _k("demand_days", [f"{_SRC}:DAYS"], [7, 14, 28],
       note="days of transcripts the census population reaches back from --now (#1151)"),
    _k("demand_floor", [f"{_SRC}:FLOOR"], [1, 2],
       note="draws every stratum gets before the rest go by output tokens (#1151)"),
    _k("demand_idle_gap", [f"{_SRC}:IDLE_GAP_S"], [120, 600, 1800],
       note="seconds between two records past which the gap counts as idle, not a subtask's wall time (#1151)"),
    _k("demand_min_final", [f"{_SRC}:MIN_FINAL"], [20, 200, 2000],
       note="final-count messages the output-token fit needs before partial counts are estimated (#1151)"),
    _k("demand_request_cap", [f"{_SRC}:REQUEST_CAP"], [500, 1500, 4000],
       note="characters of a request a labeller's packet keeps (#1151)"),
    _k("demand_result_cap", [f"{_SRC}:RESULT_CAP"], [300, 600, 1500],
       note="characters of the final assistant text a labeller's packet keeps (#1151)"),
    _k("demand_step_cap", [f"{_SRC}:STEP_CAP"], [60, 100, 200],
       note="characters of one tool step a labeller's packet keeps (#1151)"),
    _k("demand_steps", [f"{_SRC}:STEPS"], [5, 15, 30],
       note="tool steps a labeller's packet lists (#1151)"),
    _k("replay_agree_min", [f"{_REPLAY}:AGREE_MIN"], [0.9, 0.95, 0.99],
       note="share of units two temperature-0 replays must grade alike (#1161)"),
    _k("replay_control_max", [f"{_REPLAY}:CONTROL_MAX"], [0.05, 0.1, 0.2],
       note="as-is rate of the does-not-fit control at or below which it reads as near zero (#1161)"),
    _k("replay_judge_timeout", [f"{_REPLAY}:JUDGE_TIMEOUT_S"], [120.0, 600.0, 1800.0],
       note="seconds one claude -p judge or plant call may take before it counts as ungraded (#1161)"),
    _k("replay_reject_min", [f"{_REPLAY}:REJECT_MIN"], [0.8, 0.9, 0.95],
       note="share of planted wrong answers the judge must grade not_usable before its grades count (#1161)"),
    _k("replay_result_cap", [f"{_REPLAY}:RESULT_CAP"], [1500, 4000, 12000],
       note="characters of a unit's final text a replay packet keeps for plants (#1161)"),
]

NOT_GATING = {
    f"{_REPLAY}:ask_local->delegate.complete(temperature)": "the replay asks at temperature 0 by design, so two "
                                                              "replays can be compared grade for grade (#1161)",
    f"{_SRC}:public_repo->subprocess.run(timeout)": "how long gh may take to say a repo is public; a timeout "
                                                     "counts it private, so its name is masked (#1151)",
    f"{_SRC}:Msg.tokens_in": "a message's measured input tokens (#1151)",
    f"{_SRC}:Unit.tokens_out_recorded": "a unit's output tokens as its records carry them, partial counts "
                                        "included (#1151)",
    f"{_SRC}:Unit.active_s": "a unit's measured wall time, summed from its records (#1151)",
    f"{_SRC}:Unit.tokens_in": "a unit's measured input tokens, summed from its messages (#1151)",
    f"{_SRC}:Unit.tokens_out": "a unit's measured output tokens, summed from its messages (#1151)",
}
