"""Schema 39: text-classification and structured-prediction file under decide. #423."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 39


def data(conn) -> None:
    # text-classification and structured-prediction file under decide;
    # a code row whose card says so moves too. #423.
    retractions._relane_the_laneless_from_the_card(conn)
    retractions._relane_from_the_card(conn)
