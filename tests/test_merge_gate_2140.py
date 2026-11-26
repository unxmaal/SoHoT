"""A merge gate pass killed mid-suite leaves a pending verdict that the next poll tests again, with no manual step. #2140."""
from __future__ import annotations

import pytest

from harness import merge_gate as mg
from harness import owner_actions as oa
from tests.test_merge_gate_2110 import Suite, _pass, world  # noqa: F401 - the fixture
from tests.test_needs_you_2134 import HOST, band, client, cond, gather, keys, press  # noqa: F401 - the fixtures


class Killed(BaseException):
    """What a SIGKILL leaves of a pass: nothing after the suite call, and the lock let go with the process."""


def _dying(argv, cwd, env, capture=False):
    raise Killed()


def _die(world, only=7):
    with pytest.raises(Killed):
        mg.run_pass(world["live"], gh=world["hub"], run=_dying, say=lambda m: None, only=only)


def _finish(job):
    from harness import workqueue as wq
    with wq._store() as c:
        c.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.DONE, job["id"]))
        c.commit()


def test_a_pass_killed_mid_suite_is_run_again_by_the_next_poll_and_reaches_a_verdict(world):
    head = world["pr"](7, {"x": "x\n"})
    first = mg.queue(world["live"], refs=lambda src: "one")
    _die(world)
    _finish(first)
    assert world["hub"].said(head)[-1][0] == "pending" and "running" in world["hub"].said(head)[-1][1]
    assert mg.stranded() and head in mg.stranded()
    again = mg.queue(world["live"], refs=lambda src: "one")
    assert again and again["id"] != first["id"], "the refs did not move; the stranded pending status queues it"
    rows, suite = _pass(world)
    assert [r["state"] for r in rows if r["pr"]] == [mg.SUCCESS] and suite.ran
    assert world["hub"].said(head)[-1][0] == "success"
    assert mg.stranded() == {} and mg.opened() == {}
    _finish(again)
    assert mg.queue(world["live"], refs=lambda src: "one") is None


def test_a_pass_that_is_really_running_is_not_started_twice(world):
    head = world["pr"](7, {"x": "x\n"})
    seen = []

    class Watching(Suite):
        def __call__(self, argv, cwd, env, capture=False):
            seen.append((mg.stranded(), mg.queue(world["live"], refs=lambda src: "one"), mg.queue(world["live"], refs=lambda src: "two")))
            return super().__call__(argv, cwd, env, capture)
    mg.queue(world["live"], refs=lambda src: "one")
    rows, _ = _pass(world, Watching())
    assert seen and all(s == ({}, None, None) for s in seen), "a held lock is a live pass, not a stranded one"
    assert rows[-1]["state"] == mg.SUCCESS and world["hub"].said(head)[-1][0] == "success"


def test_a_pass_that_finds_the_lock_held_is_run_by_the_holder_when_it_lets_go(world):
    world["pr"](7, {"x": "x\n"})
    head8, inner = [], []

    class Opening(Suite):
        def __call__(self, argv, cwd, env, capture=False):
            if not head8:
                head8.append(world["pr"](8, {"y": "y\n"}))
                inner.append(mg.run_pass(world["live"], gh=world["hub"], run=Suite(fails="make"), say=lambda m: None))
            return super().__call__(argv, cwd, env, capture)
    rows, _ = _pass(world, Opening())
    assert inner == [[]]
    assert world["hub"].said(head8[0])[-1][0] == "success", "the holder ran the pass the contender could not"
    assert {r["pr"]["number"] for r in rows if r["pr"]} == {7, 8}
    assert not mg._again_path().exists()


def test_a_contender_whose_holder_died_leaves_a_mark_the_poll_queues_for(world):
    world["pr"](7, {"x": "x\n"})
    mg._again_path().touch()
    assert mg.stranded()
    assert mg.queue(world["live"], refs=lambda src: "one")
    rows, _ = _pass(world)
    assert rows and not mg._again_path().exists() and mg.stranded() == {}


def test_a_tree_whose_passes_died_too_often_is_left_to_the_button(world):
    head = world["pr"](7, {"x": "x\n"})
    mg.queue(world["live"], refs=lambda src: "one")
    for _ in range(mg.RETRY_MAX):
        _die(world)
    from harness import workqueue as wq
    with wq._store() as c:
        c.execute("UPDATE jobs SET state = ?", (wq.DONE,))
        c.commit()
    assert head in mg.stranded() and mg.retestable() == {}
    assert mg.queue(world["live"], refs=lambda src: "one") is None


def test_a_closed_pull_requests_pending_status_is_dropped_by_the_next_pass(world):
    head = world["pr"](7, {"x": "x\n"})
    _die(world)
    assert head in mg.opened()
    world["hub"].prs.clear()
    _pass(world)
    assert mg.opened() == {}


def test_the_band_names_a_stranded_verdict_and_its_button_queues_a_pass(world, tmp_path, client, monkeypatch):
    head = world["pr"](7, {"x": "x\n"})
    assert "gate-stranded" not in keys(gather(tmp_path))
    _die(world)
    c = cond(gather(tmp_path), "gate-stranded")
    assert c["fix"] == [{"action": "gate_again", "arg": ""}] and head[:8] in c["why"]
    ran = []
    monkeypatch.setattr(oa, "run_verb", lambda argv, run=None: ran.append(argv) or {"rc": 0, "out": "queued"})
    _, section = band(client)
    press(client, section, "gate_again")
    assert ran == [["merge-gate", "--queue"]]


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/merge_gate.py:_track")
def test_a_second_pending_post_replaces_the_first_and_a_final_one_removes_it(world):
    mg.post("h" * 40, mg.PENDING, "first", world["hub"], started=True)
    mg.post("h" * 40, mg.PENDING, "second", world["hub"], started=True)
    assert mg.opened() == {"h" * 40: {"text": "second", "tries": 2}}
    mg.post("h" * 40, mg.SUCCESS, "done", world["hub"])
    assert mg.opened() == {}


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/merge_gate.py:opened:except")
def test_an_unreadable_record_is_a_stranded_pass_not_nothing_and_the_next_pass_mends_it(world):
    world["pr"](7, {"x": "x\n"})
    mg._open_path().write_text("{not json", encoding="utf-8")
    assert mg.opened() != {} and mg.stranded() != {}
    _pass(world)
    assert mg.opened() == {} and mg.stranded() == {}
