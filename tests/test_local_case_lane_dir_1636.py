"""soh audit fails on a local case filed outside its lane's directory, which one-lane loads skip (#1636)."""
import shutil

import pytest

from evals import core
from harness import live_audit
from tests.test_live_audit import _checks, config, live  # noqa: F401

CASE = core.SHIPPED / "svg" / "chart-bars.yaml"


def _plant(local, lane):
    dest = (local / lane if lane else local) / CASE.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(CASE, dest)
    return dest


def test_a_case_in_its_own_lane_dir_passes(live, tmp_path):
    local = tmp_path / "cases"
    _plant(local, "svg")
    assert [c.modality for c in core.load_suite(tmp_path / "none", local, "svg")] == ["svg"]
    check = _checks(live_audit.audit(live, cases=local))["local_cases_in_lane_dir"]
    assert check["ok"], check


@pytest.mark.parametrize("lane", ["decide", ""])
def test_a_case_in_another_lanes_dir_or_the_root_fails_naming_its_path(live, tmp_path, lane):
    local = tmp_path / "cases"
    bad = _plant(local, lane)
    assert core.load_suite(tmp_path / "none", local, "svg") == []
    got = live_audit.audit(live, cases=local)
    check = _checks(got)["local_cases_in_lane_dir"]
    assert not check["ok"] and not got["ok"]
    assert str(bad) in check["detail"] and "declares lane svg" in check["detail"]
    assert f"sits in {lane or 'the case root'}" in check["detail"]


def test_the_audit_reads_this_homes_case_tree_by_default(live):
    bad = _plant(core.local_root(), "web")
    check = _checks(live_audit.audit(live))["local_cases_in_lane_dir"]
    assert not check["ok"] and str(bad) in check["detail"]


def test_an_unreadable_local_case_fails(live, tmp_path):
    bad = tmp_path / "cases" / "svg" / "broken.yaml"
    bad.parent.mkdir(parents=True)
    bad.write_text("id: [unclosed\n", encoding="utf-8")
    check = _checks(live_audit.audit(live, cases=bad.parent.parent))["local_cases_in_lane_dir"]
    assert not check["ok"] and str(bad) in check["detail"]


def test_no_local_case_tree_passes(live, tmp_path):
    assert _checks(live_audit.audit(live, cases=tmp_path / "absent"))["local_cases_in_lane_dir"]["ok"]
