"""`soh gauntlet review`: the review questions a diff raises, for classes no detector can find (#492 D, #1785)."""

from gauntlet import review

from tests.gauntlet.registry import REGISTRY

SNAP = [{"id": "seam", "heading": "A seam", "tier": 3, "trigger": "t?", "test_shape": "s."}]


def test_the_committed_snapshot_has_a_trigger_for_every_class():
    missing = [c["id"] for c in REGISTRY.snapshot() if not c.get("trigger") or not c.get("test_shape")]
    assert not missing


def test_only_code_lines_in_production_code_are_read_unless_a_class_names_its_paths():
    index = {"seam": {"review": r"subprocess"}}
    changed = {"README.md": [(1, "subprocess")], "harness/a.py": [(1, "# subprocess"), (2, "subprocess.run(x)")],
               "tests/test_a.py": [(1, "subprocess.run(x)")], "evals/cases/agent/x.py": [(1, "subprocess")],
               "evals/run.py": [(1, "subprocess.run(y)")]}
    assert review.fire(changed, index, SNAP, REGISTRY.code_paths)[0]["where"] == ["evals/run.py:1", "harness/a.py:2"]
    index["seam"]["review_paths"] = r"^tests/"
    assert review.fire(changed, index, SNAP, REGISTRY.code_paths)[0]["where"] == ["tests/test_a.py:1"]
