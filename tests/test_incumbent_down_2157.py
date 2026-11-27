"""#2157: a pair whose incumbent's runner failed on its own is recorded once, raised to needs-you, and never measured again."""
import argparse

import pytest

from harness import adopt, incumbent_down, needs_you, reasons
from harness import memory_store as ms
from harness.commands import loop_steps as steps
from harness.commands import measure as measure_cmd
from tests.test_resume_813 import _sweep

INC = "llamacpp:imajev-4b-Q8_0"
NIMBLE = "bespokelabs/Bespoke-Nimble-9B"
WHY = "stopped: the incumbent imajev-4b-Q8_0 answered none of its first 5 case(s), every one harness_error (boom); no comparison to make (#1656)"


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: INC)
    monkeypatch.setattr(measure_cmd.paths, "home", lambda: tmp_path)
    monkeypatch.setattr(incumbent_down, "path", lambda: tmp_path / incumbent_down.FILE)
    monkeypatch.setattr(measure_cmd.test_weights, "refused", lambda name, sweep: None)
    conn = ms.connect()
    try:
        ms.record(conn, ms.Seen(name=NIMBLE, source="t", lane="decide", resolved=NIMBLE))
        ms.decide(conn, NIMBLE, "screened", tier=ms.SCREEN, reason="candidate")
        conn.commit()
    finally:
        conn.close()


class Silent:
    def __init__(self):
        self.argvs = []

    def __call__(self, argv, **kw):
        self.argvs.append(argv)
        return measure_cmd.Launched(78, WHY + "\n", False, 1.0)


def _ns(**kw):
    return argparse.Namespace(**{"lane": "", "repeat": 1, "effect": 0.4, "power_budget_min": 60.0, **kw})


def _state(name):
    conn = ms.connect()
    try:
        return dict(conn.execute("SELECT v.outcome, v.reason, v.failure_class FROM proposals p JOIN verdicts v "
                                 "ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone())
    finally:
        conn.close()


def test_a_silent_incumbent_is_one_attempt_one_record_and_a_needs_you_mark(monkeypatch, world):
    fake = Silent()
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    got = measure_cmd._measure(_ns(), {"name": NIMBLE, "lane": "decide"}, [], _sweep())
    assert got == measure_cmd.watch.SILENT and len(fake.argvs) == 1
    assert _state(NIMBLE) == {"outcome": "queued", "reason": reasons.HARNESS, "failure_class": reasons.HARNESS_ERROR}
    conn = ms.connect()
    try:
        assert NIMBLE not in [r["name"] for r in measure_cmd.measurable(conn, 25, "")]
    finally:
        conn.close()
    marks = incumbent_down.read()
    assert marks["decide"]["runner"] == INC and marks["decide"]["pair"] == NIMBLE
    report = {"stops": {"incumbent": needs_you.read_incumbent()}}
    (item,) = needs_you._incumbent(report)
    assert "decide" in item["title"] and INC in item["why"]


def test_a_screened_pair_is_in_the_measure_queue_before_it_runs(world):
    conn = ms.connect()
    try:
        assert NIMBLE in [r["name"] for r in measure_cmd.measurable(conn, 25, "")]
    finally:
        conn.close()


def test_a_dry_run_records_and_marks_nothing(monkeypatch, world):
    monkeypatch.setattr(measure_cmd, "_launch", Silent())
    measure_cmd._measure(_ns(dry_run=True), {"name": NIMBLE, "lane": "decide"}, [], _sweep())
    assert _state(NIMBLE)["outcome"] == "screened" and incumbent_down.read() == {}


def test_the_sweep_stops_asking_after_one_incumbent_stop_or_three_other_failures():
    one = f"measure {NIMBLE}{incumbent_down.LABEL}"
    assert steps._worn([one]) == one
    other = f"measure {NIMBLE}"
    assert steps._worn([other, other]) == ""
    assert steps._worn([other] * steps.MEASURE_TRIES) == other
    assert steps._worn(["disk", "measure a", "measure b"]) == ""


def test_a_screened_pair_keeps_its_weights_when_its_test_ends_without_a_verdict(monkeypatch):
    seen = {}
    monkeypatch.setattr("harness.disk.sweep", lambda **kw: seen.update(kw))
    measure_cmd.test_weights.release("x/y")
    assert "screened" in seen["keep_states"]


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/incumbent_down.py:read:except")
def test_an_unreadable_mark_is_not_reported_as_no_mark(world, tmp_path):
    assert incumbent_down.read() == {}
    (tmp_path / incumbent_down.FILE).write_text("{not json", encoding="utf-8")
    assert incumbent_down.read()["?"]["why"] == "unreadable mark file"


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/incumbent_down.py:mark")
def test_a_mark_is_keyed_by_lane_and_a_later_stop_replaces_it(world):
    incumbent_down.mark("tts", "tts:a", "p1", "x", now=1)
    incumbent_down.mark("code", "llamacpp:b", "p2", "y", now=2)
    incumbent_down.mark("tts", "tts:a", "p3", "z", now=3)
    got = incumbent_down.read()
    assert set(got) == {"tts", "code"} and got["tts"]["pair"] == "p3" and got["code"]["pair"] == "p2"


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/incumbent_down.py:clear")
def test_a_finished_run_clears_only_its_own_lane(world):
    incumbent_down.mark("tts", "tts:a", "p1", "x")
    incumbent_down.mark("code", "llamacpp:b", "p2", "y")
    incumbent_down.clear("tts")
    assert set(incumbent_down.read()) == {"code"}
