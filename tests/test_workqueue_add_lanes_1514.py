"""A queue add for a one-lane job reads that lane's case files only (#1514)."""
import os
import sys
from pathlib import Path

import pytest

from evals import core, run
from harness import baseline
from harness import workqueue as wq

REPO = ["uv", "run", "python", "-m", "evals.run", "--modality", "repo", "--candidates",
        "claude-code:claude-opus-5-5", "--repeat", "1", "--split", "all", "--out", "runs/opus"]


def _plant_unreadable(lane: str) -> Path:
    bad = core.local_root() / lane / "broken.yaml"
    bad.parent.mkdir(parents=True)
    bad.write_text("id: [unclosed\n", encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(bad, 0)
    return bad


def test_an_add_reads_no_other_lanes_case_files(monkeypatch):
    _plant_unreadable("web")
    seen = []
    parse = core._parse
    monkeypatch.setattr(core, "_parse", lambda p: seen.append(Path(p)) or parse(p))
    job = wq.add(REPO, title="opus repo")
    assert job["state"] == wq.PENDING
    assert seen, "the add never read the repo lane"
    lanes = (core.SHIPPED / "repo", core.local_root() / "repo")
    assert [p for p in seen if not any(d in p.parents for d in lanes)] == []


def test_a_broken_case_in_another_lane_does_not_hide_a_lanes_exam():
    _plant_unreadable("web")
    assert baseline.exam_cases("repo")


@pytest.mark.parametrize("lane", sorted(core.MODALITIES))
def test_a_lane_read_gives_the_cases_the_whole_suite_gives(lane, tmp_path):
    local = tmp_path / "local"
    (local / lane).mkdir(parents=True)
    whole = [c for c in core.load_suite(core.SHIPPED, local) if c.modality == lane]
    one = [c for c in core.load_suite(core.SHIPPED, local, lane) if c.modality == lane]
    assert [c.id for c in one] == [c.id for c in whole]
    assert core.cases_digest(one) == core.cases_digest(whole)


def test_every_shipped_case_sits_in_its_lanes_directory():
    assert core.misfiled(core.SHIPPED) == []


def test_all_still_reads_every_lane():
    args = run.parse_args(["--modality", "all"])
    got = {c.modality for c in run.load_selected(args)}
    assert {"web", "svg", "decide"} <= got
