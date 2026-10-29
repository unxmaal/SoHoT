"""Sites of soh baseline, the three-arm table per workload (#687), none of which cuts anything."""

KNOBS: list = []

NOT_GATING = {
    "evals/workload_baseline.py:lane_rows->_row(local_s)":
        "seconds a lane with no stored run spent, summed into the GPU-minutes column; it reports, it decides nothing (#687)",
}
