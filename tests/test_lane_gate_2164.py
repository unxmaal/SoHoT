"""#2164: a lane whose power plan at its adopt effect is under lane_gate_power takes no challengers; the owner can open it for a while."""
import json
from types import SimpleNamespace

import pytest

from harness import fetching, holdout, lane_gate, lanes, paused, power
from harness import memory_store as ms
from harness import status_buttons, status_view
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd

NOW = 2_000_000_000.0


def _plan(p, unmeasured=False):
    return SimpleNamespace(power=p, unmeasured=unmeasured, cases_needed=400, rho=0.5)


def _powers(monkeypatch, **by_lane):
    def fake(conn, lane, split, receipts=None, effect=None):
        return lane_gate.Calc("k", "spec", {}, None, (), [], {}, 5, 0.1, 0, 0.05,
                              _plan(by_lane.get(lane, 0.95), lane in UNMEASURED))
    monkeypatch.setattr(lane_gate, "calc", fake)


UNMEASURED: set = set()


class _Open:
    def __init__(self, c):
        self.c = c

    def __getattr__(self, name):
        return getattr(self.c, name)

    def close(self):
        pass


@pytest.fixture
def conn():
    UNMEASURED.clear()
    c = ms.connect()
    yield c
    c.close()


def _queue(c, name, lane, tier=ms.INSPECT, outcome="queued"):
    ms.record(c, ms.Seen(name=name, source="test", url="", why="", relevance=0, kind="candidate",
                         registry=ms.HUGGINGFACE, lane=lane, resolved=name))
    ms.decide(c, name, outcome, tier=tier if outcome == "queued" else ms.SCREEN, detail="fits")


def test_a_lane_under_the_gate_power_is_closed_and_one_over_it_is_open(conn, monkeypatch):
    _powers(monkeypatch, code=0.07, svg=0.85)
    got = lane_gate.gate_for(conn, "code")
    assert got and got.power == 0.07 and got.cases_needed == 400 and "lane_gate_power 0.80" in got.why
    assert lane_gate.gate_for(conn, "svg") is None
    assert set(lane_gate.shut(conn, ["code", "svg", ""])) == {"code"}


def test_an_unmeasured_incumbent_is_a_guess_and_never_closes_its_lane(conn, monkeypatch):
    _powers(monkeypatch, code=0.07)
    UNMEASURED.add("code")
    assert lane_gate.gate_for(conn, "code") is None


def test_a_queued_candidate_in_a_closed_lane_is_not_fetched_and_keeps_its_row(conn, monkeypatch):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())
    _powers(monkeypatch, code=0.07, svg=0.85)
    _queue(conn, "org/in-code", "code")
    _queue(conn, "org/in-svg", "svg")
    assert [r["name"] for r in fetching.queued(conn)] == ["org/in-svg"]
    assert fetching.row(conn, "org/in-code") is None and fetching.row(conn, "org/in-svg")["name"] == "org/in-svg"
    assert conn.execute("SELECT state FROM proposals WHERE name = 'org/in-code'").fetchone()[0] == "queued"


def test_a_screen_run_leaves_the_closed_lanes_candidate_ranked_with_the_gate_reason(conn, monkeypatch):
    monkeypatch.setattr(ms, "connect", lambda *a, **k: _Open(conn))
    _powers(monkeypatch, code=0.07, svg=0.85)
    _queue(conn, "org/in-code", "code")
    _queue(conn, "org/in-svg", "svg")
    plan = [{"name": "org/in-code", "lane": "code", "modality": "code", "state": "ready"},
            {"name": "org/in-svg", "lane": "svg", "modality": "svg", "state": "ready"}]
    got = screen_cmd._open_lanes(plan, record=True)
    assert [r["name"] for r in got] == ["org/in-svg"]
    row = conn.execute("SELECT p.state, v.detail FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                       "WHERE p.name = 'org/in-code'").fetchone()
    assert row["state"] == "queued" and "code lane closed to challengers" in row["detail"]


def test_a_screened_candidate_in_a_closed_lane_is_not_measured_and_a_paused_run_stays_paused(conn, monkeypatch):
    _powers(monkeypatch, code=0.07, svg=0.85)
    _queue(conn, "org/in-code", "code", outcome="screened")
    _queue(conn, "org/in-svg", "svg", outcome="screened")
    assert [r["name"] for r in measure_cmd.measurable(conn, 100, "code")] == []
    assert "org/in-svg" in [r["name"] for r in measure_cmd.measurable(conn, 100, "svg")]
    for lane in ("code", "svg"):
        paused.save(conn, lane=lane, inc_spec="inc", spec=f"org/p-{lane}", proposal=f"org/p-{lane}", out=f"/o/{lane}",
                    ident={}, plan={}, done=3, total=9, looks=[])
    assert [r["name"] for r in measure_cmd.resume_first(conn, [])] == ["org/p-svg"]
    rows = {r["lane"]: r for r in paused.waiting(conn)}
    assert set(rows) == {"code", "svg"} and rows["svg"]["why"] == ""
    assert "code lane closed to challengers" in rows["code"]["why"]


def test_the_owners_override_opens_the_lane_until_it_expires(conn, monkeypatch):
    _powers(monkeypatch, code=0.07)
    got = lane_gate.open_lane(conn, "code", now=NOW, ttl=3600)
    assert got["kind"] == "lane-open:code" and got["said"] == lane_gate.OWNER and got["until"] == NOW + 3600
    assert lane_gate.shut(conn, ["code"], now=NOW + 60) == {}
    assert set(lane_gate.shut(conn, ["code"], now=NOW + 3601)) == {"code"}
    st = lane_gate.status(conn, now=NOW + 60)
    assert [g["lane"] for g in st["opened"]] == ["code"] and st["closed"] == [] and st["opened"][0]["until"] == NOW + 3600
    assert lane_gate.close_lane(conn, "code", now=NOW + 120)["released_at"] == NOW + 120
    assert set(lane_gate.shut(conn, ["code"], now=NOW + 121)) == {"code"}
    assert lane_gate.close_lane(conn, "code", now=NOW + 122) is None
    with pytest.raises(ValueError):
        lane_gate.open_lane(conn, "no-such-lane")


SC = "a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null"


@pytest.mark.gauntlet(SC, site="harness/lane_gate.py:override:holds")
@pytest.mark.gauntlet(SC, site="harness/lane_gate.py:close_lane:holds")
def test_another_machines_override_neither_opens_nor_is_closed_by_this_ones(conn):
    other = conn.execute("INSERT INTO machines (fingerprint, first_seen, last_seen) VALUES ('other-machine', 0, 0)").lastrowid
    conn.execute("INSERT INTO holds (machine_id, kind, held_at, said, until) VALUES (?,?,?,?,?)",
                 (other, "lane-open:code", NOW, "owner", NOW + 3600))
    conn.commit()
    assert lane_gate.override(conn, "code", NOW + 1) is None and lane_gate.close_lane(conn, "code", NOW + 1) is None
    lane_gate.open_lane(conn, "code", now=NOW)
    assert lane_gate.close_lane(conn, "code", NOW + 2) is not None
    assert conn.execute("SELECT released_at FROM holds WHERE machine_id = ?", (other,)).fetchone()[0] is None


def test_the_override_is_not_a_benchmarks_or_gpu_hold(conn, monkeypatch):
    from harness import hold
    lane_gate.open_lane(conn, "code", now=NOW)
    assert hold.actives(conn, NOW + 1) == []


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/lane_gate.py:override")
def test_the_longest_lasting_override_in_force_is_the_one_read(conn):
    lane_gate.open_lane(conn, "code", now=NOW, ttl=7200)
    lane_gate.open_lane(conn, "code", now=NOW + 10, ttl=60)
    assert lane_gate.override(conn, "code", NOW + 20)["until"] == NOW + 7200


def test_the_gate_decides_as_the_power_table_does_over_every_lane(conn, monkeypatch, capsys):
    from harness import cli
    from harness import adopt as adopt_mod
    monkeypatch.setattr(adopt_mod, "default_for", lambda lane, fallback, *a, **k: "inc")

    def profile(lane, receipts, c):
        split = holdout.for_lane(lane)
        draws = {cid: [1.0, 0.0] if i % 3 else [1.0, 1.0] for i, cid in enumerate(split.holdout + split.dev)}
        return "k", "spec", draws, None, (), []
    monkeypatch.setattr(lane_gate, "profile", profile)
    assert cli.main(["adopt", "--json", "--power"]) == 0
    table = {r["lane"]: r for r in json.loads(capsys.readouterr().out)["lanes"] if r["cases"]}
    assert table
    for threshold in (0.0, 0.2, 0.5, 0.8, 0.99):
        monkeypatch.setattr(lane_gate, "GATE_POWER", threshold)
        for lane, row in table.items():
            assert (lane_gate.gate_for(conn, lane) is not None) == (not row["unmeasured_plan"] and row["power"] < threshold)
    monkeypatch.setattr(lane_gate, "GATE_POWER", power.TARGET)
    assert {lane for lane, r in table.items() if not r["enough"]} == {lane for lane in table if lane_gate.gate_for(conn, lane)}


def _gated_status():
    g = {"lane": "code", "power": 0.07, "effect": 0.1, "holdout": 135, "cases_needed": 376, "more_holdout": 241,
         "more_cases": 804, "why": "x", "issue": lane_gate.GROWTH_ISSUE}
    return {"threshold": 0.8, "closed": [g], "opened": [{**g, "lane": "tts", "until": NOW + 3600, "said": "owner"}],
            "issue": lane_gate.GROWTH_ISSUE, "as_of": NOW}


def test_the_status_page_offers_open_for_a_closed_lane_and_close_for_an_opened_one():
    r = {"lane_gate": _gated_status()}
    got = status_buttons.offered(r)
    assert got["lane_open"] == {"code"} and got["lane_close"] == {"tts"}
    page = status_view._closed_lanes(r["lane_gate"], NOW, status_buttons.closed_lanes(r, "tok"))
    assert "needs 241 more holdout cases" in page and lane_gate.GROWTH_ISSUE in page
    assert "action='status/action'" in page and "value='lane_open'" in page and "value='lane_close'" in page
    assert "not read" in status_view._closed_lanes({"error": "boom"}, NOW)


def test_reverify_and_knob_sweeps_do_not_consult_the_gate():
    from pathlib import Path
    for mod in ("reverify.py", "sweeps.py"):
        assert "lane_gate" not in (Path(lane_gate.__file__).parent / mod).read_text(encoding="utf-8")


def test_a_named_challenger_is_refused_in_a_closed_lane_until_the_owner_opens_it(conn, monkeypatch, capsys):
    from harness import cli
    _powers(monkeypatch, code=0.07)
    ran = []
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", lambda a, row, *x: ran.append(row["name"]) or 0)
    assert cli.main(["adopt", "--lane", "code", "--challenger", "org/x"]) == 1 and ran == []
    assert "code lane closed to challengers" in capsys.readouterr().err
    lane_gate.open_lane(conn, "code")
    assert cli.main(["adopt", "--lane", "code", "--challenger", "org/x"]) == 0 and ran == ["org/x"]
