"""infovore's squashed fix commits as repo-lane tasks, subjects ending (#issue) (#pr). #889."""
from __future__ import annotations

import sys

from evals.importers import history

LANE = history.LANE
LICENSE = history.LICENSE
REVISION = "219940e42104c3e625a6642713e856e2bb2305fc"
REPO = history.Repo(
    "history_infovore", "infovore", "https://github.com/unxmaal/infovore.git", "unxmaal/infovore",
    REVISION, pytest_args=("--import-mode=importlib",), dropped={})
SOURCE, DATASET, URL = REPO.source, REPO.dataset, REPO.home
RESPONDERS = history.RESPONDERS
passes = history.passes


def fetch() -> list[dict]:
    return history.fetch(src=REPO)


def convert(row: dict):
    return history.convert(row, REPO, sys.modules[__name__])
