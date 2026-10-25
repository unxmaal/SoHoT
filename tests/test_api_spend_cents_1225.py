"""#1225: an API charge under half a cent is reported as a non-zero amount, never $0.00."""
import re
from pathlib import Path

import pytest

from harness import api_spend
from harness import memory_store as ms

ROOT = Path(__file__).resolve().parent.parent
OPUS = {"model_name": "cloud-opus", "litellm_params": {"model": "anthropic/claude-opus-5-5",
                                                         "input_cost_per_token": 4e-06,
                                                         "output_cost_per_token": 2e-05}}


def _row(cost, caller="purpose:smoke"):
    return {"at": 1000.0, "alias": "cloud-opus", "model": "claude-opus-5-5", "call_id": "c", "caller": caller,
            "client": "curl", "prompt_tokens": 15, "completion_tokens": 4, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "cost_usd": cost, "cost_source": "litellm"}


@pytest.mark.parametrize("x, want", [(0.00014, "$0.00014"), (0.000149, "$0.00015"), (0.0003, "$0.0003"),
                                     (0.006, "$0.006"), (0.01, "$0.01"), (0.5, "$0.50"), (12.345, "$12.35"),
                                     (200, "$200.00"), (0, "$0.00"), (-0.00014, "-$0.00014"),
                                     (-1.5, "-$1.50")])
def test_usd_keeps_cents_and_shows_sub_cent_amounts(x, want):
    assert api_spend.usd(x) == want


def _report(capsys, cost):
    from harness import cli, morning
    from harness.commands import morning as morning_cmd
    conn = ms.connect()
    try:
        api_spend.record(conn, _row(cost))
    finally:
        conn.close()
    assert cli.main(["api-spend"]) == 0
    out = capsys.readouterr().out
    conn = ms.connect()
    try:
        brief = morning_cmd.api_spend_line(morning.api_spend(conn))
    finally:
        conn.close()
    return out, brief


def test_a_sub_cent_charge_shows_on_the_total_the_caller_and_the_morning_line(capsys):
    out, brief = _report(capsys, 0.00014)
    total = next(ln for ln in out.splitlines() if "api spend" in ln)
    caller = next(ln for ln in out.splitlines() if "purpose:smoke" in ln and "req" in ln)
    assert "$0.00014 of $200.00" in total and "top caller purpose:smoke $0.00014" in total
    assert caller.rstrip().endswith("$0.00014")
    assert "$0.00014 of $200.00" in brief


def test_a_charge_over_a_dollar_keeps_cents(capsys):
    out, _ = _report(capsys, 12.345)
    assert "$12.35 of $200.00" in out and "$187.66 left" in out


def test_a_sub_cent_run_estimate_is_not_zero():
    got = {"estimate": 0.0003, "remaining": 199.99986, "unmeasured": []}
    assert api_spend.describe(got) == "api spend estimate $0.0003, $200.00 left of api_budget"


def test_no_api_spend_module_formats_dollars_inline():
    inline = re.compile(r"\$\{[^}]*:[^}]*\.\d+f\}")
    hits = [f"{p}:{n}" for p in ("harness/api_spend.py", "harness/commands/api_spend.py")
            for n, ln in enumerate((ROOT / p).read_text(encoding="utf-8").splitlines(), 1) if inline.search(ln)]
    assert hits == [], "format dollars with api_spend.usd: " + ", ".join(hits)
