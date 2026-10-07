"""The gauntlet registry binds this repo's defects to the skill's classes (#492)."""

import os
from pathlib import Path

import pytest

from tests.gauntlet import classes, core

REPO = Path(__file__).resolve().parent.parent

SKILL_MD = """\
# The gauntlet

## How to run it

No tier here, so this is not a class.

# The corpus

## A fact about the harness recorded as a verdict on the subject

**Tier:** 2, plus a scanner for the classifier's location (tier 1).

## A platform primitive assumed universal

**Tier:** 1. Nearly all of these are scannable.

# Adding an entry

**Tier**. not a class either, the heading is a top-level one.
"""

GENERAL_MD = """\
# The general corpus

## Provenance rule (read this first)

## 10. Encoding assumed

**Tier:** 1 in Python (`open`/`read_text` with no `encoding=`).
"""


def fixture_snapshot():
    return core.parse_skill(SKILL_MD, "SKILL.md") + core.parse_skill(GENERAL_MD, "general-corpus.md")


def fixture_defects():
    return {1: {"title": "a", "created": "2026-09-01T00:00:00Z"},
            2: {"title": "b", "created": "2026-09-02T00:00:00Z"},
            3: {"title": "c", "created": "2026-09-03T00:00:00Z"}}


def fixture_registry():
    index = {
        "a-fact-about-the-harness-recorded-as-a-verdict-on-the-subject": {
            "instances": [{"issue": 1}, {"rule": 270}], "scanners": []},
        "a-platform-primitive-assumed-universal": {
            "instances": [{"issue": 2}],
            "scanners": ["tests/test_portability.py::test_no_script_uses_a_bsd_only_df_flag"]},
    }
    pending = {"guard-built-never-invoked": {"tier": 2, "instances": [{"issue": 3}]}}
    return index, pending, {}


def check(index, pending, unclassified, snapshot=None, defects=None):
    return core.problems(index, pending, unclassified,
                         fixture_snapshot() if snapshot is None else snapshot,
                         fixture_defects() if defects is None else defects, REPO)


def test_a_heading_becomes_a_stable_kebab_id():
    assert core.slug("A part's cost reported as the whole's") == "a-part-s-cost-reported-as-the-whole-s"
    assert core.slug("10. Encoding assumed") == "encoding-assumed"
    assert core.slug("Silent truncation, or a partial read assumed complete") == \
        "silent-truncation-or-a-partial-read-assumed-complete"


def test_only_headings_with_a_tier_are_classes():
    snap = fixture_snapshot()
    assert [c["id"] for c in snap] == [
        "a-fact-about-the-harness-recorded-as-a-verdict-on-the-subject",
        "a-platform-primitive-assumed-universal",
        "encoding-assumed"]
    assert [c["tier"] for c in snap] == [2, 1, 1]
    assert snap[2]["source"] == "general-corpus.md"


def test_the_skill_s_bite_count_is_read_as_an_integer():
    text = "# The corpus\n\n## A class\n\n**Bitten:** 10+ in two days.\n\n**Tier:** 2.\n\n## Another\n\n**Tier:** 1.\n"
    snap = core.parse_skill(text, "SKILL.md")
    assert [c["bitten"] for c in snap] == [10, None]


def test_505_is_bound_to_the_shared_resource_class_not_unclassified():
    assert 505 not in classes.UNCLASSIFIED
    assert {"issue": 505} in classes.INDEX["a-shared-fixed-resource-in-tests"]["instances"]


def test_pending_is_empty_once_the_skill_defines_every_proposed_class():
    assert classes.PENDING == {}


def test_the_fixture_registry_is_clean():
    assert check(*fixture_registry()) == []


def test_a_class_the_skill_does_not_define_is_refused():
    index, pending, unc = fixture_registry()
    index["made-up-class"] = {"instances": [{"issue": 1}], "scanners": []}
    assert any("made-up-class" in p and "not in the skill" in p for p in check(index, pending, unc))


def test_a_pending_class_the_skill_now_defines_must_move_into_the_index():
    index, pending, unc = fixture_registry()
    pending["encoding-assumed"] = {"tier": 1, "instances": [{"issue": 3}]}
    assert any("encoding-assumed" in p and "move it" in p for p in check(index, pending, unc))


@pytest.mark.parametrize("entry, needle", [
    ({"instances": [{"issue": 1}]}, "missing scanners"),
    ({"scanners": []}, "missing instances"),
    ({"instances": [], "scanners": []}, "no instance"),
    ({"instances": [{"pr": 1}], "scanners": []}, "bad instance"),
    ({"instances": [{"issue": "1"}], "scanners": []}, "bad instance"),
])
def test_an_entry_missing_a_field_is_refused(entry, needle):
    index, pending, unc = fixture_registry()
    index["a-platform-primitive-assumed-universal"] = entry
    assert any(needle in p for p in check(index, pending, unc)), check(index, pending, unc)


def test_a_pending_entry_needs_a_tier():
    index, pending, unc = fixture_registry()
    pending["guard-built-never-invoked"] = {"instances": [{"issue": 3}]}
    assert any("missing tier" in p for p in check(index, pending, unc))


def test_an_instance_issue_must_be_in_the_snapshot():
    index, pending, unc = fixture_registry()
    index["a-platform-primitive-assumed-universal"]["instances"].append({"issue": 999})
    assert any("#999" in p and "snapshot" in p for p in check(index, pending, unc))


def test_every_snapshot_defect_is_bound_or_explained():
    index, pending, unc = fixture_registry()
    del pending["guard-built-never-invoked"]
    assert any("#3" in p and "no class" in p for p in check(index, pending, unc))
    assert check(index, pending, {3: "upstream model behaviour"}) == []
    assert any("#3" in p and "reason" in p for p in check(index, pending, {3: ""}))


def test_an_issue_cannot_be_both_classified_and_unclassified():
    index, pending, unc = fixture_registry()
    assert any("#1" in p and "both" in p for p in check(index, pending, {1: "why"}))


def test_a_scanner_that_does_not_exist_is_refused():
    index, pending, unc = fixture_registry()
    index["a-platform-primitive-assumed-universal"]["scanners"] = [
        "tests/test_portability.py::test_that_was_never_written"]
    assert any("test_that_was_never_written" in p for p in check(index, pending, unc))
    index["a-platform-primitive-assumed-universal"]["scanners"] = ["tests/no_such_file.py::test_x"]
    assert any("no_such_file" in p for p in check(index, pending, unc))


def test_a_tier_1_class_with_no_scanner_yet_is_a_listed_gap_not_a_failure():
    index, pending, unc = fixture_registry()
    index["a-platform-primitive-assumed-universal"]["scanners"] = []
    assert check(index, pending, unc) == []
    assert core.unscanned(index, fixture_snapshot()) == ["a-platform-primitive-assumed-universal"]
    index["a-platform-primitive-assumed-universal"]["scanners"] = [
        "tests/test_portability.py::test_no_script_uses_a_bsd_only_df_flag"]
    assert core.unscanned(index, fixture_snapshot()) == []


def test_the_registry_is_clean():
    snapshot = core.load_snapshot()
    defects = core.load_defects()
    assert core.problems(classes.INDEX, classes.PENDING, classes.UNCLASSIFIED,
                         snapshot, defects, REPO) == []


def test_ids_are_unique_across_the_snapshot_and_pending():
    ids = [c["id"] for c in core.load_snapshot()]
    assert len(ids) == len(set(ids))
    assert not set(classes.PENDING) & set(ids)


def test_the_snapshot_is_what_the_skill_says(tmp_path):
    skill = core.skill_dir()
    if not (skill / "SKILL.md").is_file():
        pytest.skip("no gauntlet skill on this machine (CI); drift is checked where it lives")
    assert core.read_skill(skill) == core.load_snapshot(), \
        "the skill changed: run `python -m tests.gauntlet snapshot-skill` and rebind"


def test_the_skill_location_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("GAUNTLET_SKILL_DIR", str(tmp_path))
    assert core.skill_dir() == tmp_path
    monkeypatch.delenv("GAUNTLET_SKILL_DIR")
    assert core.skill_dir() == Path(os.path.expanduser("~")) / ".claude" / "skills" / "gauntlet"


def test_read_skill_parses_both_files(tmp_path):
    (tmp_path / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (tmp_path / "general-corpus.md").write_text(GENERAL_MD, encoding="utf-8")
    assert core.read_skill(tmp_path) == fixture_snapshot()
