"""Closing the loop: a defect closed without a class is found, offline in CI and by gh at a desk (#492, #1785)."""

import subprocess

import pytest
from gauntlet import registry

from tests.gauntlet.registry import REGISTRY


def test_the_commits_here_close_no_unbound_defect():
    log = subprocess.run(["git", "log", "-n", "2000", "--format=%B%x00"], cwd=REGISTRY.root,
                         capture_output=True, text=True, encoding="utf-8")
    if log.returncode != 0:
        pytest.skip(f"no git history here: {log.stderr.strip()}")
    messages = [m for m in log.stdout.split("\x00") if m.strip()]
    assert registry.unbound_closures(messages, set(REGISTRY.defects()), REGISTRY.index, REGISTRY.pending,
                                     REGISTRY.unclassified) == []
