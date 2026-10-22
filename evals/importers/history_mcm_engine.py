"""mcm-engine's merged fix PRs as repo-lane tasks: merge commits whose branch names the issue. #889."""
from __future__ import annotations

import re
import sys

from evals.importers import history

LANE = history.LANE
LICENSE = history.LICENSE
REVISION = "a5b9741db49e7bfbdbfe321b65921dc08664da8e"
REPO = history.Repo(
    "history_mcm_engine", "mcm-engine", "https://github.com/unxmaal/mcm-engine.git", "unxmaal/mcm-engine",
    REVISION, subject=re.compile(r"^Merge pull request #(?P<pr>\d+) from [^/\s]+/(?:[^/\s]+/)*(?P<issue>\d+)-"),
    merges=True, pytest_args=("-o", "pythonpath=src"), extras=("dev",),
    solution=("proposed fix", "proposed direction", "deliverables"), dropped={})
SOURCE, DATASET, URL = REPO.source, REPO.dataset, REPO.home
RESPONDERS = history.RESPONDERS
passes = history.passes


def fetch() -> list[dict]:
    return history.fetch(src=REPO)


def convert(row: dict):
    return history.convert(row, REPO, sys.modules[__name__])
