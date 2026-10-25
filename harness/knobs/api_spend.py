"""Knobs of the API credit spend guard (#1214)."""
from harness.knobs.base import _k

KNOBS = [
    _k("api_budget", ["harness/api_spend.py:BUDGET_USD"], [0.0, 200.0, 1000.0], limit="api_budget", unit="usd",
       note="dollars of prepaid API credit metered gateway aliases may spend since the recorded start; "
            "the balance on 2026-10-25 (#1214)"),
]
