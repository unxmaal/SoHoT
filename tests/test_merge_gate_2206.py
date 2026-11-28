"""A merge gate pass tests the tree that has waited longest, skips what merged or closed, and a --pr call waits for the lock and reports its own verdict. #2206."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pytest

from harness import exclusive
from harness import merge_gate as mg
from harness.commands import merge_gate as cmd
from tests.test_merge_gate_2110 import Suite, _pass, world  # noqa: F401 - the fixture


def _at(monkeypatch, stamp: str) -> None:
    monkeypatch.setenv("GIT_COMMITTER_DATE", stamp)


def _numbers(rows) -> list[int]:
    return [r["pr"]["number"] for r in rows if r["pr"]]


def test_the_tree_that_has_waited_longest_is_tested_first_whatever_its_number(world, monkeypatch):
    _at(monkeypatch, "2026-11-28T10:00:00Z")
    world["pr"](9, {"a9": "1\n"}, world["base"])
    _at(monkeypatch, "2026-11-28T08:00:00Z")
    world["pr"](7, {"a7": "1\n"}, world["base"])
    _at(monkeypatch, "2026-11-28T09:00:00Z")
    world["pr"](8, {"a8": "1\n"}, world["base"])
    rows, _ = _pass(world)
    assert _numbers(rows) == [7, 8, 9]


def test_a_pull_request_that_merged_or_closed_while_another_was_tested_is_not_tested(world, monkeypatch):
    _at(monkeypatch, "2026-11-28T08:00:00Z")
    world["pr"](7, {"a7": "1\n"}, world["base"])
    _at(monkeypatch, "2026-11-28T09:00:00Z")
    gone = world["pr"](8, {"a8": "1\n"}, world["base"])

    class Closes(Suite):
        def __call__(self, argv, cwd, env, capture=False):
            world["hub"].prs[:] = [p for p in world["hub"].prs if p["number"] != 8]
            return super().__call__(argv, cwd, env, capture)

    rows, suite = _pass(world, Closes())
    assert _numbers(rows) == [7]
    assert [s for s, _ in world["hub"].said(gone)] == ["pending"] and "queued" in world["hub"].said(gone)[0][1]
    assert not any(gone[:12] in step for step in suite.ran)


def test_a_pull_request_opened_during_a_pass_is_tested_in_it_in_its_turn(world, monkeypatch):
    _at(monkeypatch, "2026-11-28T08:00:00Z")
    world["pr"](7, {"a7": "1\n"}, world["base"])

    class Opens(Suite):
        def __call__(self, argv, cwd, env, capture=False):
            if not self.ran:
                _at(monkeypatch, "2026-11-28T09:00:00Z")
                world["pr"](8, {"a8": "1\n"}, world["base"])
            return super().__call__(argv, cwd, env, capture)

    rows, _ = _pass(world, Opens())
    assert _numbers(rows) == [7, 8]


def test_a_tree_that_errors_is_tried_once_in_a_pass_not_forever(world):
    world["pr"](7, {"x": "x\n"})
    calls = []

    def broken(argv, cwd, env, capture=False):
        calls.append(argv)
        raise OSError("no make on PATH")

    rows = mg.run_pass(world["live"], only=7, gh=world["hub"], run=broken, say=lambda m: None)
    assert [r["state"] for r in rows] == [mg.ERROR] and len(calls) == 1


class Clock:
    """A clock the sleeps move, and a hook each sleep runs."""

    def __init__(self, on_sleep=None):
        self.now, self.slept, self.on_sleep = 0.0, 0, on_sleep

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept += 1
        assert self.slept < 100, "the wait has no deadline"
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(self.slept)


@pytest.fixture
def held():
    """The lock another pass holds; call release() to let go."""
    fd = os.open(mg.root() / "lock", os.O_RDWR | os.O_CREAT, 0o644)
    assert exclusive._take(fd)
    state = {"open": True}

    def release():
        if state["open"]:
            exclusive._release(fd)
            os.close(fd)
            state["open"] = False

    yield release
    release()


def test_a_pr_call_waits_for_the_holder_then_reports_the_verdict_the_holders_pass_gave_its_tree(world, held):
    head = world["pr"](7, {"x": "x\n"})
    holder = Suite()

    def let_go(n):
        if n == 2:
            held()
            mg.run_pass(world["live"], gh=world["hub"], run=holder, say=lambda m: None)

    clock = Clock(let_go)
    said = []
    suite = Suite()
    rows = mg.run_pass(world["live"], only=7, gh=world["hub"], run=suite, say=said.append, wait=60,
                       sleep=clock.sleep, clock=clock)
    assert holder.ran and suite.ran == [], "the holder tested the tree; the waiter does not test it again"
    assert [(r["pr"]["number"], r["state"], r.get("cached")) for r in rows] == [(7, mg.SUCCESS, True)]
    assert rows[0]["head"] == head and any("waiting" in m for m in said)


@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/merge_gate.py:_lock")
def test_a_pr_call_whose_holder_never_lets_go_gives_up_at_its_deadline_without_a_verdict(world, held):
    world["pr"](7, {"x": "x\n"})
    clock = Clock()
    suite = Suite()
    rows = mg.run_pass(world["live"], only=7, gh=world["hub"], run=suite, say=lambda m: None, wait=12,
                       sleep=clock.sleep, clock=clock)
    assert rows == [] and suite.ran == [] and clock.slept == 3


def test_a_pr_call_that_finds_the_lock_free_tests_its_own_tree_and_a_call_without_wait_never_waits(world, held):
    world["pr"](7, {"x": "x\n"})
    clock = Clock()
    assert mg.run_pass(world["live"], only=7, gh=world["hub"], run=Suite(), say=lambda m: None,
                       sleep=clock.sleep, clock=clock) == [] and clock.slept == 0
    held()
    rows = mg.run_pass(world["live"], only=7, gh=world["hub"], run=Suite(), say=lambda m: None, wait=30,
                       sleep=clock.sleep, clock=clock)
    assert [(r["state"], r.get("cached")) for r in rows] == [(mg.SUCCESS, None)]


def test_the_command_waits_for_a_pr_by_default_and_exits_1_with_no_verdict(monkeypatch, capsys):
    seen = {}

    def fake(repo, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(mg, "run_pass", fake)
    ns = dict(pr=7, repo="x", again=False, queue=False, wait=None)
    assert cmd.cmd_merge_gate(argparse.Namespace(**ns)) == 1 and seen["wait"] == mg.WAIT_S
    assert cmd.cmd_merge_gate(argparse.Namespace(**{**ns, "pr": None})) == 0 and seen["wait"] == 0.0
    assert cmd.cmd_merge_gate(argparse.Namespace(**{**ns, "wait": 5.0})) == 1 and seen["wait"] == 5.0


def test_the_repositorys_own_seam_names_store_code_and_a_migration_and_not_the_gate_itself():
    ci = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    seam = re.compile(mg._SEAM.search(ci).group(1))
    for path in ("harness/store.py", "harness/store_service.py", "harness/memory_store/migrations/v109.py", "deploy/postgres/compose.yaml"):
        assert seam.search(path), path
    for path in ("harness/merge_gate.py", "tests/test_merge_gate_2206.py", "harness/cuts.py"):
        assert not seam.search(path), path
