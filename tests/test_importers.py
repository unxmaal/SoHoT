"""The importer framework and the code lane's LeetCodeDataset importer, on a recorded slice. #603."""
import ast
import json
from pathlib import Path

import pytest
import yaml

from evals import importers
from evals.core import load_cases
from evals.importers import leetcode
from harness.checks import code

SLICE = Path(__file__).resolve().parent / "fixtures" / "importers" / "leetcode-slice.jsonl"
SHIPPED = Path(__file__).resolve().parents[1] / "evals" / "cases" / "code" / "leetcode"


def _rows():
    return [json.loads(line) for line in SLICE.read_text(encoding="utf-8").splitlines()]


def _imported(tmp_path, rows=None):
    return importers.run("leetcode", root=tmp_path, rows=_rows() if rows is None else rows)


def test_the_registry_is_a_list_of_unique_sources_each_naming_its_lane_and_license():
    names = [s.name for s in importers.REGISTRY]
    assert len(names) == len(set(names))
    for s in importers.REGISTRY:
        mod = importers.module(s.name)
        assert s.lane and mod.LICENSE in importers.ALLOWED_LICENSES
        assert mod.REVISION and len(mod.REVISION) == 40


def test_an_unknown_source_is_refused_naming_the_known_ones():
    with pytest.raises(ValueError, match="leetcode"):
        importers.module("nope")


def test_provenance_carries_dataset_revision_license_item_date_and_transform():
    p = importers.provenance(leetcode, item="two-sum", transform="t", date="2025-01-02")
    assert {"source", "dataset", "url", "revision", "license", "item", "date",
            "transform", "importer"} <= set(p)
    assert p["revision"] == leetcode.REVISION and p["date"] == "2025-01-02"


def test_writing_is_deterministic_and_replaces_only_the_sources_own_directory(tmp_path):
    keep = tmp_path / "code" / "hand.yaml"
    keep.parent.mkdir(parents=True)
    keep.write_text("id: hand\n", encoding="utf-8")
    first = {p: p.read_bytes() for p in _imported(tmp_path)}
    stale = tmp_path / "code" / "leetcode" / "gone.yaml"
    stale.write_text("id: gone\n", encoding="utf-8")
    second = {p: p.read_bytes() for p in _imported(tmp_path)}
    assert first == second and first
    assert not stale.exists() and keep.exists()


def test_imported_cases_load_as_code_cases_with_their_reference_beside_them(tmp_path):
    written = _imported(tmp_path)
    cases = load_cases(tmp_path / "code")
    assert {c.id for c in cases} == {p.stem for p in written}
    for c in cases:
        assert c.modality == "code" and len(c.assertions["checks"]) >= 3
        assert (c.source.parent / "reference" / f"{c.id}.py").is_file()


def test_tree_and_list_helpers_are_skipped_since_an_answer_cannot_see_them(tmp_path):
    ids = {p.stem for p in _imported(tmp_path)}
    assert "lc3319" not in ids
    assert len(ids) == 5


def test_a_check_naming_a_helper_is_dropped_and_candidate_becomes_the_entry_point():
    stmt = ast.parse("assert candidate(n = 3) == inf").body[0]
    assert leetcode.assert_to_check(stmt, "Solution().f") is None
    stmt = ast.parse("assert candidate(nums = [1, 2]) == 3").body[0]
    assert leetcode.assert_to_check(stmt, "Solution().f") == "Solution().f(nums=[1, 2]) == 3"
    assert leetcode.assert_to_check(ast.parse("x = 1").body[0], "Solution().f") is None


def test_an_item_whose_checks_all_expect_one_value_is_skipped_as_constant_passable():
    row = _rows()[0]
    row["test"] = "def check(candidate):\n" + "".join(
        f"    assert candidate(n = {n}, queries = [[0, 1]]) == [1]\n" for n in range(2, 6))
    assert leetcode.convert(row) is None


def test_provenance_on_every_imported_case_names_the_item_and_its_date(tmp_path):
    for p in _imported(tmp_path):
        att = yaml.safe_load(p.read_text(encoding="utf-8"))["attribution"]
        assert att["revision"] == leetcode.REVISION and att["license"] == "Apache-2.0"
        assert att["date"][:4] in ("2024", "2025") and att["item"] in p.stem


def test_the_negative_control_separates_reference_from_constant_on_the_slice(tmp_path):
    _imported(tmp_path)
    cases = load_cases(tmp_path / "code")
    got = importers.negative_control(cases, leetcode.RESPONDERS, leetcode.passes)
    assert got["reference"] == (len(cases), len(cases))
    assert got["none"][0] == 0 and got["zero"][0] == 0


def test_soh_cases_import_writes_the_cases(tmp_path, monkeypatch, capsys):
    from harness import cli
    monkeypatch.setattr(leetcode, "fetch", lambda: _rows())
    assert cli.main(["cases", "import", "leetcode", "--out", str(tmp_path)]) == 0
    assert len(list((tmp_path / "code" / "leetcode").glob("*.yaml"))) == 5
    assert "5 cases" in capsys.readouterr().out


def test_soh_cases_control_reports_each_responder(tmp_path, monkeypatch, capsys):
    from harness import cli
    _imported(tmp_path)
    assert cli.main(["cases", "control", "leetcode", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "reference 5/5" in out and "none 0/5" in out


SHIPPED_CASES = load_cases(SHIPPED) if SHIPPED.is_dir() else []


def test_the_shipped_import_matches_its_provenance_and_is_unique():
    assert len(SHIPPED_CASES) >= 300
    for c in SHIPPED_CASES:
        att = yaml.safe_load(c.source.read_text(encoding="utf-8"))["attribution"]
        assert att["revision"] == leetcode.REVISION and att["item"] and att["date"]
        assert (c.source.parent / "reference" / f"{c.id}.py").is_file()


#: A recorded slice of the shipped import; the full set is checked by `soh cases control leetcode`.
SHIPPED_SLICE = SHIPPED_CASES[::40]


@pytest.mark.parametrize("case", SHIPPED_SLICE, ids=lambda c: c.id)
def test_a_shipped_slice_passes_its_reference_and_fails_a_constant(case):
    ref = (case.source.parent / "reference" / f"{case.id}.py").read_text(encoding="utf-8")
    assert code.check(ref, case.assertions["checks"]).ok
    assert not leetcode.passes(case, leetcode.RESPONDERS["none"](case))


def test_libyaml_reads_an_imported_case_exactly_as_the_pure_loader_does():
    from evals import core
    for c in SHIPPED_SLICE:
        text = c.source.read_text(encoding="utf-8")
        assert yaml.load(text, Loader=core._LOADER) == yaml.safe_load(text)


def test_imported_text_is_not_scanned_as_this_projects_prose(tmp_path):
    from harness import assertions
    for p in _imported(tmp_path):
        assert assertions.is_imported(p.read_text(encoding="utf-8"))
        ref = p.parent / "reference" / f"{p.stem}.py"
        assert assertions.is_imported(ref.read_text(encoding="utf-8"))
