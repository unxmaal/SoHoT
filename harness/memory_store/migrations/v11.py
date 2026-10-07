"""Schema 11: rerun the harness-refusal retraction with the longer phrase list."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 11


def data(conn) -> None:
    # The phrase list grew: a screen subprocess that resolved a PARENT
    # directory's virtualenv could not import our own eval package, and
    # four freshly fetched candidates were recorded BROKEN, which is
    # terminal, for something they never did. The retraction is DERIVED
    # from the current lists rather than naming rows, which is the lesson
    # of #230 -- naming rows by hand missed the second member of the same
    # class.
    retractions._retract_harness_refusals(conn)
