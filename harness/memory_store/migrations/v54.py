"""Schema 54: a reranker tagged text-embeddings-inference is released, then laned. #563."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 54


def data(conn) -> None:
    retractions._release_retrievers_marked_embeddings(conn)
    retractions._relane_the_laneless_from_lineage(conn)
