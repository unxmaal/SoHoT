"""#2168: a lane whose incumbent is marked down takes no fetch, screen or measure; reverify still runs and a passing one clears the mark."""
from types import SimpleNamespace

import pytest

from harness import fetching, incumbent_down, lane_gate, needs_you, paused, power, reverify
from harness import memory_store as ms
from harness import status_buttons, status_view
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from tests.test_reverify import (NOW, VERSIONS, DAY, _queue_and_finish, cases, check, conn, on, powered,  # noqa: F401
                                 queued, record_run)

pytestmark = pytest.mark.usefixtures("powered")


@pytest.fixture(autouse=True)
def marks(tmp_path, monkeypatch):
    monkeypatch.setattr(incumbent_down, "path", lambda: tmp_path / incumbent_down.FILE)
    monkeypatch.setattr(lane_gate, "calc", lambda conn, lane, split, receipts=None, effect=None: lane_gate.Calc(
        "k", "spec", {}, None, (), [], {}, 5, 0.1, 0, 0.05,
        SimpleNamespace(power=0.95, unmeasured=False, cases_needed=100, rho=0.5)))


def _queue(c, name, lane, outcome="queued"):
    ms.record(c, ms.Seen(name=name, source="test", url="", why="", relevance=0, kind="candidate",
                         registry=ms.HUGGINGFACE, lane=lane, resolved=name))
    ms.decide(c, name, outcome, tier=ms.INSPECT if outcome == "queued" else ms.SCREEN, detail="fits")


def _down(lane="code", at=NOW - 3600):
    incumbent_down.mark(lane, "llamacpp:inc", "org/pair", "the incumbent answered none of its first cases", now=at)


class _Open:
    def __init__(self, c):
        self.c = c

    def __getattr__(self, name):
        return getattr(self.c, name)

    def close(self):
        pass


def test_a_down_mark_closes_its_lane_whatever_the_power_and_the_owners_override(conn):
    assert lane_gate.shut(conn, ["code", "svg"]) == {}
    _down("code")
    got = lane_gate.shut(conn, ["code", "svg"])
    assert set(got) == {"code"} and got["code"].kind == "incumbent_down"
    assert "incumbent llamacpp:inc is down" in got["code"].why and "reverify" in got["code"].why
    lane_gate.open_lane(conn, "code")
    assert set(lane_gate.shut(conn, ["code"])) == {"code"}


def test_an_unreadable_mark_file_closes_no_lane(conn, tmp_path):
    (tmp_path / incumbent_down.FILE).write_text("{not json", encoding="utf-8")
    assert lane_gate.shut(conn, ["code", "svg"]) == {}


def test_the_next_sweep_fetches_screens_and_measures_nothing_in_the_lane(conn, monkeypatch):
    monkeypatch.setattr(ms, "connect", lambda *a, **k: _Open(conn))
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())
    _down("code")
    _queue(conn, "org/in-code", "code")
    _queue(conn, "org/in-svg", "svg")
    assert [r["name"] for r in fetching.queued(conn)] == ["org/in-svg"]
    plan = [{"name": "org/in-code", "lane": "code", "modality": "code", "state": "ready"},
            {"name": "org/in-svg", "lane": "svg", "modality": "svg", "state": "ready"}]
    assert [r["name"] for r in screen_cmd._open_lanes(plan, record=True)] == ["org/in-svg"]
    row = conn.execute("SELECT p.state, v.detail FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                       "WHERE p.name = 'org/in-code'").fetchone()
    assert row["state"] == "queued" and "incumbent llamacpp:inc is down" in row["detail"]
    _queue(conn, "org/m-code", "code", outcome="screened")
    _queue(conn, "org/m-svg", "svg", outcome="screened")
    assert [r["name"] for r in measure_cmd.measurable(conn, 100, "code")] == []
    assert "org/m-svg" in [r["name"] for r in measure_cmd.measurable(conn, 100, "svg")]
    paused.save(conn, lane="code", inc_spec="inc", spec="org/p", proposal="org/p", out="/o", ident={}, plan={},
                done=3, total=9, looks=[])
    assert measure_cmd.resume_first(conn, []) == []


def test_the_reverify_of_a_lane_with_a_down_incumbent_is_queued_though_nothing_else_moved(conn):
    record_run(conn, "code", cases("q3-4b", 10), at=NOW - DAY)
    assert check(conn)["planned"][0]["skip"] == "nothing moved"
    _down("code", at=NOW - 60)
    got = check(conn)
    [entry] = got["queued"]
    assert entry["triggers"] == [[reverify.INCUMBENT, "incumbent llamacpp:inc is down: the incumbent answered none of its first cases"]]
    assert len(queued(conn)) == 1


def test_a_passing_reverify_clears_the_mark_and_a_failing_one_keeps_it(conn):
    record_run(conn, "code", cases("q3-4b", 10), at=NOW - DAY)
    _down("code", at=NOW - 60)
    _queue_and_finish(conn, cases("q3-4b", 0), failure_class="timeout")
    check(conn, now=NOW + 120)
    assert set(incumbent_down.read()) == {"code"}
    reverify.check(conn, now=NOW + 200, lane="code", force=True)
    _queue_and_finish(conn, cases("q3-4b", 10))
    got = check(conn, now=NOW + 400)
    assert [s["outcome"] for s in got["settled"]] == [reverify.PASSED]
    assert incumbent_down.read() == {}
    assert lane_gate.shut(conn, ["code"]) == {}


def test_a_retry_runs_again_though_the_last_flagged_rerun_is_not_due(conn):
    record_run(conn, "code", cases("q3-4b", 10), at=NOW - DAY)
    _down("code", at=NOW - 60)
    _queue_and_finish(conn, cases("q3-4b", 0), failure_class="timeout")
    check(conn, now=NOW + 120)
    assert "re-run again in" in check(conn, now=NOW + 200)["planned"][0]["skip"]
    got = reverify.check(conn, now=NOW + 200, lane="code", force=True)
    assert [e["lane"] for e in got["queued"]] == ["code"]


def _status():
    return lane_gate_status_with_down()


def lane_gate_status_with_down():
    return {"threshold": 0.8, "closed": [], "opened": [], "issue": lane_gate.GROWTH_ISSUE, "as_of": NOW,
            "down": [{"lane": "code", "runner": "llamacpp:inc", "pair": "org/pair", "why": "answered none", "at": NOW - 90}]}


def test_the_status_reads_the_down_lanes(conn):
    _down("code", at=NOW - 90)
    got = lane_gate.status(conn, now=NOW)
    assert [(d["lane"], d["runner"], d["why"]) for d in got["down"]] == [
        ("code", "llamacpp:inc", "the incumbent answered none of its first cases")]


def test_the_closed_lanes_panel_names_the_reason_and_offers_retry_incumbent():
    r = {"lane_gate": _status()}
    assert status_buttons.offered(r)["incumbent_retry"] == {"code"}
    page = status_view._closed_lanes(r["lane_gate"], NOW, status_buttons.closed_lanes(r, "tok"))
    assert "incumbent down" in page and "llamacpp:inc" in page and "answered none" in page
    assert "value='incumbent_retry'" in page and "Retry incumbent" in page
    assert "every lane reaches power" not in status_view._closed_lanes(r["lane_gate"], NOW)


def test_the_retry_button_runs_soh_reverify_for_that_lane():
    from harness import owner_actions as oa
    assert oa.BY_NAME["incumbent_retry"].verb("code") == ["reverify", "--lane", "code", "--retry-incumbent"]


def test_needs_you_still_shows_the_mark(conn):
    _down("code")
    assert [r["lane"] for r in needs_you.read_incumbent()["rows"]] == ["code"]


def test_a_pass_queued_before_the_mark_was_written_does_not_clear_it():
    _down("code", at=NOW)
    incumbent_down.clear("code", ran_at=NOW - 1)
    assert set(incumbent_down.read()) == {"code"}
    incumbent_down.clear("code", ran_at=NOW)
    assert incumbent_down.read() == {}
