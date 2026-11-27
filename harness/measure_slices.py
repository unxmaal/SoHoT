"""A paired measure's slices: one look interval of the budget, and whether the last is too short to launch. #1353, #1553 (#2167)."""
from __future__ import annotations

from dataclasses import replace


def slice_of(plan, elapsed: float):
    """(this launch's share of the plan, whether it is the budget's last): one look interval of what is left. #1353."""
    from harness import looks
    if plan.budget_s is None:
        return plan, True
    left = max(0.0, plan.budget_s - elapsed)
    step = float(looks.LOOK_INTERVAL_S or 0.0)
    deadline = None if plan.deadline_s is None else max(0.0, plan.deadline_s - elapsed)
    last = step <= 0 or step >= left
    return replace(plan, budget_s=left if last else step, deadline_s=deadline), last


def case_s(plan) -> list:
    """The planned seconds of one case for the incumbent and the challenger, each None when unpriced."""
    est = plan.estimate or {}
    return [est.get(f"{who}_s") and est[f"{who}_s"] * (est.get(f"{who}_calls") or 1)
            for who in ("incumbent", "challenger")]


def short_slice(plan) -> str:
    """Why the budget's last slice is too short to launch: it ends before one planned case of each side; "" if not. #1553."""
    each = case_s(plan)
    if plan.budget_s is None or not all(each) or plan.budget_s >= sum(each):
        return ""
    return f"its slice ends in {plan.budget_s:.0f}s, under one planned case of each side ({sum(each):.0f}s)"
