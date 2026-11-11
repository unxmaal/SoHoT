"""The gauntlet registry binds this repo's defects to the pinned corpus's classes (#492, #1785)."""

import shutil

import gauntlet.ratchet
from gauntlet import skill

from tests.gauntlet import classes
from tests.gauntlet.registry import REGISTRY

REGISTRY_HALF = ("test_gauntlet_registry_is_clean", "test_gauntlet_snapshot_is_the_pinned_corpus",
                 "test_gauntlet_ids_are_unique", "test_gauntlet_every_named_detector_exists",
                 "test_gauntlet_review_heuristics_are_present_and_quiet")
RATCHETS = gauntlet.ratchet.tests(REGISTRY, skill_dir=skill.corpus_dir())
globals().update({name: RATCHETS[name] for name in REGISTRY_HALF})

EXTRA_CLASS = "\n\n## A class only a newer corpus has\n\n**Bitten:** 1.\n\n**Tier:** 3.\n"


def test_505_is_bound_to_the_shared_resource_class_not_unclassified():
    assert 505 not in classes.UNCLASSIFIED
    assert {"issue": 505} in classes.INDEX["a-shared-fixed-resource-in-tests"]["instances"]


def test_pending_is_empty_once_the_skill_defines_every_proposed_class():
    assert classes.PENDING == {}


def test_a_newer_local_skill_does_not_change_this_suite(tmp_path, monkeypatch):
    newer = tmp_path / "home" / ".claude" / "skills" / "gauntlet"
    shutil.copytree(skill.corpus_dir(), newer)
    with open(newer / "SKILL.md", "a", encoding="utf-8") as f:
        f.write(EXTRA_CLASS)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GAUNTLET_SKILL_DIR", str(newer))
    assert gauntlet.ratchet.snapshot_drift(REGISTRY), "the newer corpus must read as drift, or this proves nothing"
    RATCHETS["test_gauntlet_snapshot_is_the_pinned_corpus"]()

