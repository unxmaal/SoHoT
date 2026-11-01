"""openspec/: every scenario names a real test or says untested; every module sits in one capability. #1363."""
import json
import shutil
from pathlib import Path

import pytest

from harness import specs

FIX = Path(__file__).parent / "fixtures" / "specs_1363"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(FIX / "good", tmp_path / "r")
    for txt in (tmp_path / "r" / "openspec" / "specs").rglob("spec.txt"):
        txt.rename(txt.with_suffix(".md"))
    return tmp_path / "r"


def _spec(root):
    return root / "openspec" / "specs" / "widget" / "spec.md"


def _edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_the_good_fixture_passes(root):
    assert specs.check(root) == []


def test_a_planted_spec_naming_a_test_that_does_not_exist_fails(root):
    shutil.copy(FIX / "planted_missing_test.txt", _spec(root))
    got = specs.check(root)
    assert len(got) == 1
    assert "tests/proof.py::test_widget_flies" in got[0] and "no such test" in got[0]


def test_the_real_specs_pass():
    assert specs.check(REPO) == []


def test_a_missing_test_file_fails(root):
    _edit(_spec(root), "tests/proof.py::test_widget_turns", "tests/gone.py::test_widget_turns")
    assert any("tests/gone.py" in p and "no such file" in p for p in specs.check(root))


def test_a_class_method_must_exist_in_that_class(root):
    _edit(_spec(root), "TestGadget::test_gadget_hums", "TestGadget::test_gadget_sings")
    assert any("TestGadget::test_gadget_sings" in p for p in specs.check(root))


def test_a_test_line_must_name_a_test_function_not_a_helper(root):
    _edit(_spec(root), "::test_widget_turns", "::helper")
    assert any("::helper" in p for p in specs.check(root))


def test_a_scenario_without_a_test_line_fails(root):
    _edit(_spec(root), "Test: tests/proof.py::test_widget_turns\n", "")
    assert any("Pushed" in p and "Test:" in p for p in specs.check(root))


def test_a_scenario_with_two_test_lines_fails(root):
    _edit(_spec(root), "Test: untested\n", "Test: untested\nTest: tests/proof.py::test_widget_turns\n")
    assert any("Left alone" in p and "one Test:" in p for p in specs.check(root))


def test_a_malformed_test_line_fails(root):
    _edit(_spec(root), "Test: untested", "Test: someday")
    assert any("someday" in p for p in specs.check(root))


def test_a_scenario_needs_when_and_then(root):
    _edit(_spec(root), "- **WHEN** nothing pushes the widget\n", "")
    assert any("Left alone" in p and "WHEN" in p for p in specs.check(root))
    _edit(_spec(root), "- **THEN** it rests\n", "")
    assert any("Left alone" in p and "THEN" in p for p in specs.check(root))


def test_a_requirement_says_shall_or_must(root):
    _edit(_spec(root), "The widget MUST rest", "The widget rests")
    assert any("Resting" in p and "SHALL" in p for p in specs.check(root))


def test_a_requirement_needs_a_scenario(root):
    with _spec(root).open("a", encoding="utf-8") as f:
        f.write("\n### Requirement: Glowing\nThe widget SHALL glow.\n")
    assert any("Glowing" in p and "no scenario" in p for p in specs.check(root))


def test_a_spec_needs_a_requirements_section(root):
    _edit(_spec(root), "## Requirements", "## Things")
    assert any("## Requirements" in p for p in specs.check(root))


def test_a_module_in_no_capability_fails(root):
    (root / "harness" / "orphan.py").write_text('"""Nobody owns me."""\n', encoding="utf-8")
    assert any("harness/orphan.py" in p and "no capability" in p for p in specs.check(root))


def test_a_module_in_two_capabilities_fails(root):
    _edit(root / "openspec" / "capabilities.yaml", "      - evals/gadget.py",
          "      - evals/gadget.py\n      - harness/sub/part.py")
    assert any("harness/sub/part.py" in p and "widget" in p and "gadget" in p for p in specs.check(root))


def test_a_map_entry_that_matches_no_module_fails(root):
    _edit(root / "openspec" / "capabilities.yaml", "      - evals/gadget.py",
          "      - evals/gadget.py\n      - evals/gone.py")
    assert any("evals/gone.py" in p and "matches no module" in p for p in specs.check(root))


def test_a_written_spec_must_exist_and_a_spec_must_be_mapped(root):
    _edit(root / "openspec" / "capabilities.yaml", "spec: pending", "spec: written\n    untested: 0")
    assert any("gadget" in p and "spec.md" in p for p in specs.check(root))
    shutil.copytree(root / "openspec" / "specs" / "widget", root / "openspec" / "specs" / "stray")
    assert any("stray" in p and "not in" in p for p in specs.check(root))


def test_a_pending_capability_has_no_spec_file(root):
    _edit(root / "openspec" / "capabilities.yaml", "spec: written", "spec: pending")
    assert any("widget" in p and "pending" in p for p in specs.check(root))


def test_untested_scenarios_are_held_at_the_pinned_count(root):
    _edit(_spec(root), "Test: tests/proof.py::test_widget_turns", "Test: untested")
    assert any("widget" in p and "untested" in p and "2" in p for p in specs.check(root))


def test_binding_an_untested_scenario_asks_for_the_pin_to_come_down(root):
    _edit(_spec(root), "Test: untested", "Test: tests/proof.py::test_widget_turns")
    assert any("widget" in p and "lower" in p for p in specs.check(root))


def test_counts_per_capability(root):
    got = {c["name"]: c for c in specs.counts(root)}
    assert got["widget"] == {"name": "widget", "spec": "written", "scenarios": 3, "bound": 2, "untested": 1}
    assert got["gadget"] == {"name": "gadget", "spec": "pending", "scenarios": 0, "bound": 0, "untested": 0}


def test_untested_lists_each_unbound_scenario(root):
    assert specs.untested(root) == [("widget", "Resting", "Left alone")]


def test_soh_specs_prints_counts(root, monkeypatch, capsys):
    from harness import cli
    monkeypatch.setattr(specs, "ROOT", root)
    assert cli.main(["specs", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {c["name"]: c["untested"] for c in out["capabilities"]} == {"widget": 1, "gadget": 0}
    assert out["problems"] == []


def test_soh_specs_fails_and_names_the_problem(root, monkeypatch, capsys):
    from harness import cli
    shutil.copy(FIX / "planted_missing_test.txt", _spec(root))
    monkeypatch.setattr(specs, "ROOT", root)
    assert cli.main(["specs"]) == 1
    assert "test_widget_flies" in capsys.readouterr().out


def test_the_module_walk_never_reads_tests_or_fixtures():
    mods = specs.modules(REPO)
    assert mods and all(m.startswith(("harness/", "evals/")) and m.endswith(".py") for m in mods)
