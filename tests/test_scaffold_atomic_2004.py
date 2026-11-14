"""A refused or failed scaffold leaves the tree as it found it, and a summary already citing its issue cites it once. #2004."""
import stat
import sys
from pathlib import Path

import pytest

from harness import cli, scaffold

CAPS = ("trees: [harness, evals]\ncapabilities:\n  - name: deploy-guard\n    summary: x\n    modules:\n"
        "      - harness/old.py\n  - name: bare\n    summary: no modules list\n")
CLI = "from harness.commands import old as old_cmd\n\n\ndef build(sub):\n    old_cmd.add_parser(sub)\n"
LAUNCHD = ('SERVICES="a"\ndeclare -a PERIODIC=(a)\n# a\nA_HOURS="${A_HOURS:-3}"\ndeclare -a SCHEDULER_ONLY=(a)\n'
           '_schedule() {\n    [ "$service" = a ] && hours="$A_HOURS"\n}\n')
WEIGHT = 'UNIT_OUTPUTS = {\n    "a": ("", "", "", ("a",)),\n}\n'


def tree(root: Path, **over) -> Path:
    files = {"openspec/capabilities.yaml": CAPS, "harness/cli.py": CLI, "harness/old.py": '"""old."""\n',
             "harness/commands/old.py": 'def add_parser(sub):\n    sub.add_parser("taken")\n',
             "harness/m.py": '"""m."""\nimport os\n',
             "harness/knobs/fix.py": 'KNOBS = []\n\nNOT_GATING = {\n    "harness/m.py:WAIT_S": "held",\n}\n',
             "scripts/launchd.sh": LAUNCHD, "scripts/serve-taken.sh": "#!/bin/sh\n",
             scaffold.UNIT_TABLE: WEIGHT, **over}
    for rel, text in files.items():
        if text is not None:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
    (root / "scripts/launchd.sh").chmod(0o755)
    return root


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in sorted(root.rglob("*"))}


def soh(root: Path, *args: str) -> int:
    return cli.main(["scaffold", "--root", str(root), "--issue", "1", *args])


def test_the_issues_refused_scaffold_leaves_nothing_and_its_rerun_lands(tmp_path):
    root = tree(tmp_path)
    before = snapshot(root)
    assert soh(root, "module", "harness/zz_scaffold_probe.py", "Probe. #1.", "--capability", "nope") == 2
    assert snapshot(root) == before
    assert soh(root, "module", "harness/zz_scaffold_probe.py", "Probe. #1.", "--capability", "deploy-guard") == 0
    assert (root / "harness/zz_scaffold_probe.py").read_text(encoding="utf-8").startswith('"""Probe (#1)."""\n')
    assert "      - harness/zz_scaffold_probe.py\n" in (root / scaffold.CAPABILITIES).read_text(encoding="utf-8")


@pytest.mark.parametrize("args, over", [
    (("module", "harness/p.py", "P", "--capability", "bare"), {}),
    (("module", "harness/p.py", "P", "--capability", "deploy-guard", "--command"), {"harness/cli.py": "x = 1\n"}),
    (("module", "harness/taken.py", "P", "--capability", "deploy-guard", "--command"), {}),
    (("module", "harness/p.py", "two\nlines", "--capability", "deploy-guard"), {}),
    (("timeout", "harness/m.py", "WAIT_S", "3", "--why", "again", "--area", "fix"), {}),
    (("timeout", "harness/m.py", "WAIT_S", "3", "--knob", "k_wait", "--values", "a,b", "--area", "fix"), {}),
    (("knob", "k_x", "harness/m.py:X_S", "--values", "1,b", "--note", "n", "--area", "fix"), {}),
    (("knob", "k_x", "harness/m.py:X_S", "--values", "1", "--note", "n", "--area", "../fix"), {}),
    (("not-gating", "harness/m.py:WAIT_S", "again", "--area", "fix"), {}),
    (("unit", "fresh", "soh fresh", "Fresh", "--hours", "5"), {scaffold.UNIT_TABLE: "X = 1\n"}),
    (("unit", "taken", "soh taken", "Taken", "--hours", "5"), {}),
])
def test_a_refused_scaffold_leaves_the_tree_byte_identical(tmp_path, args, over):
    root = tree(tmp_path, **over)
    before = snapshot(root)
    assert soh(root, *args) == 2
    assert snapshot(root) == before


def test_a_write_that_fails_part_way_takes_back_this_runs_files_and_restores_the_rest(tmp_path, monkeypatch):
    root = tree(tmp_path)
    before = snapshot(root)
    real = scaffold.atomic_file.replace

    def refuse(src, dst):
        if Path(dst).name == "cli.py":
            raise OSError(28, "No space left on device")
        real(src, dst)
    monkeypatch.setattr(scaffold.atomic_file, "replace", refuse)
    with pytest.raises(OSError):
        scaffold.module(root, "harness/newpkg/probe.py", "Probe", capability="deploy-guard", issue="1", command=True)
    assert snapshot(root) == before


def test_a_file_the_rollback_cannot_put_back_is_named(tmp_path, monkeypatch):
    root = tree(tmp_path)
    real, seen = scaffold.atomic_file.replace, []

    def refuse(src, dst):
        seen.append(Path(dst).name)
        if Path(dst).name == "cli.py" or seen.count("capabilities.yaml") > 1 and Path(dst).name == "capabilities.yaml":
            raise OSError(28, "No space left on device")
        real(src, dst)
    monkeypatch.setattr(scaffold.atomic_file, "replace", refuse)
    with pytest.raises(scaffold.ScaffoldError, match="could not put back: openspec/capabilities.yaml"):
        scaffold.module(root, "harness/probe.py", "Probe", capability="deploy-guard", issue="1", command=True)
    assert not (root / "harness/probe.py").exists() and not (root / "harness/commands/probe.py").exists()


def test_a_unit_keeps_the_launchd_scripts_mode_and_cites_its_issue_once(tmp_path):
    root = tree(tmp_path)
    assert soh(root, "unit", "fresh", "soh fresh", "Fresh run #1.", "--hours", "5") == 0
    script = (root / "scripts/serve-fresh.sh").read_text(encoding="utf-8")
    assert "# Fresh run, then exit. #1.\n" in script
    assert "# Fresh run, at these local hours. #1.\n" in (root / "scripts/launchd.sh").read_text(encoding="utf-8")
    if sys.platform != "win32":
        assert stat.S_IMODE((root / "scripts/launchd.sh").stat().st_mode) == 0o755
        assert stat.S_IMODE((root / "scripts/serve-fresh.sh").stat().st_mode) == 0o755


@pytest.mark.parametrize("text, cited", [
    ("Probe. #1959.", "Probe (#1959)"),
    ("Probe (#1959).", "Probe (#1959)"),
    ("Probe #19590", "Probe #19590 (#1959)"),
    ("Probe", "Probe (#1959)"),
])
def test_a_summary_ending_in_its_issue_tag_is_cited_once(text, cited):
    assert scaffold._cited(text, "#1959") == cited
