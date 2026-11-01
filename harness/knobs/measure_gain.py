"""Knobs of the measure queue's expected gain per GPU-minute (#1315)."""
from harness.knobs.base import _k

G = "harness/measure_gain.py"
E = ("2026-10-26 store copy: 38 stored paired measure runs (adopt verdicts and pauses), net gain per cell "
     "mean -0.12, median -0.048, sd 0.28, per-cell variance mean 0.147; ")

KNOBS = [
    _k("measure_gain_prior_cells", [f"{G}:PRIOR_CELLS"], [1.0, 2.0, 4.0, 16.0], unit="cells",
       note=E + "cells the prior is worth: per-cell variance over the sd squared, 0.147/0.28^2 = 1.9 (#1315)"),
    _k("measure_gain_prior_mean", [f"{G}:PRIOR_MEAN"], [-0.12, -0.05, 0.0], unit="share",
       note=E + "the median, since four sub-1B code losses (-0.6 to -0.8) pull the mean down; 6 of 38 gained (#1315)"),
    _k("measure_gain_prior_sd", [f"{G}:PRIOR_SD"], [0.1, 0.2, 0.3, 0.5], unit="share",
       note=E + "the sd across challengers before any evidence, rounded up (#1315)"),
    _k("measure_gain_related_cells", [f"{G}:RELATED_CELLS"], [0.0, 2.0, 4.0, 12.0, 48.0], unit="cells",
       note=E + "cells a relative's comparison of n cells tends to, as n*R/(n+R): per-cell variance over the spread between "
            "members; "
            "plan on code (+0.068, +0.030), plan on extract (-0.098, -0.096), four LFM2.5 on code (-0.71..-0.04), "
            "two Qwen3.8-27B on code (-0.19, -0.11) pool to sd 0.19, 0.147/0.19^2 = 4 (#1315)"),
]

NEVER_CUTS = {
    "harness/measure_gain.py:PRIOR_CELLS": "a queue-order weight; it orders the measure step and never refuses a row",
    "harness/measure_gain.py:PRIOR_MEAN": "a queue-order weight; it orders the measure step and never refuses a row",
    "harness/measure_gain.py:PRIOR_SD": "a queue-order weight; it orders the measure step and never refuses a row",
    "harness/measure_gain.py:RELATED_CELLS": "a queue-order weight; it orders the measure step and never refuses a row",
    "harness/verify.py:COST_S": "a lane's estimated seconds per verify pass; it orders the plan cheapest first and "
                                "prints its total, and every planned lane still runs",
    "harness/verify.py:Task.cost_s": "a task's estimated seconds; it orders the verify plan and prints, and never "
                                     "skips a task",
}
