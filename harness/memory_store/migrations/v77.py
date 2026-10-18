"""Schema 77: ledger_days drops its API-price dollar columns; each day's detail keeps what they held. #976."""
from __future__ import annotations

from harness.memory_store.migrations.columns import _drop_column

VERSION = 77
#: Priced Claude Code usage at API list rates, which a Max-plan login never pays.
DOLLAR_COLUMNS = ("cloud_usd", "displaced_usd", "mapped_usd", "tier")


def data(conn) -> None:
    for col in DOLLAR_COLUMNS:
        _drop_column(conn, "ledger_days", col)
