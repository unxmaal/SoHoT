"""Knobs of `soh ledger`, its launchd units and the statusline wrapper (#826)."""
from harness.knobs.base import _k

KNOBS = [
    _k("energy_every", ["scripts/launchd.sh:ENERGY_EVERY_MIN"], [1, 5, 15],
       note="minutes between macmon power readings from the energy unit (#826)"),
    _k("ledger_counterfactual", ["harness/ledger.py:COUNTERFACTUAL", "harness/ledger.py:COUNTERFACTUAL_DEFAULT"],
       ["haiku", "sonnet", "opus"],
       note="cloud tier a lane's local work is priced at as displaced dollars; printed beside every figure (#826)"),
    _k("ledger_hours", ["scripts/launchd.sh:LEDGER_HOURS"], [21, 23],
       note="local hour the ledger unit upserts today's and yesterday's ledger_days rows (#826)"),
    _k("ledger_power_gap", ["harness/ledger.py:POWER_GAP_S"], [120.0, 180.0, 600.0],
       note="seconds between two power samples beyond which the time between is uncovered, not integrated (#826)"),
    _k("ledger_power_window", ["harness/ledger.py:POWER_WINDOW_MS"], [1000, 5000, 15000],
       note="milliseconds one macmon reading averages over (#826)"),
    _k("ledger_tariff", ["harness/ledger.py:TARIFF_USD_PER_KWH"], [0.10, 0.15, 0.30],
       note="USD per kWh the energy figure is priced at; --tariff overrides per run (#826)"),
    _k("statusline_min_gap", ["harness/statusline.py:MIN_GAP_S"], [60.0, 300.0, 900.0],
       note="seconds before an unchanged rate-limit reading is logged again (#826)"),
]

NOT_GATING = {
    "harness/trends.py:MAX_SERIES": "how many series a published trend chart draws before folding into other; "
                                    "presentation only, the totals are unchanged (#827)",
    "harness/trends.py:TREND_DAYS": "how many days back the published trend charts reach; presentation only (#827)",
    "harness/ledger.py:cloud->runner(timeout)": "how long ccusage may take; a timeout reports the cloud unavailable (#826)",
    "harness/ledger.py:prices->runner(timeout)": "how long installing litellm at the pin may take to print prices; "
                                                 "a timeout leaves displaced dollars unpriced, never zero (#826)",
    "harness/commands/ledger.py:gather_compare->_dt.timedelta(days)": "one calendar day, the compared window (#868)",
}
