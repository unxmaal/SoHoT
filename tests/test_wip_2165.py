"""#2165: discovery pulls work. A lane holds at most measure_wip screened, paused and running measures; a prefilter keeps what no screen can run out of the ranked list."""
import json
import time

import pytest

from harness import discovery_flow, family, fetching, lane_gate, paused, prefilter, refetch, report, wip
from harness import memory_store as ms
from harness import status_view as sv
from harness.commands import screen as screen_cmd

GIB = 1 << 30


class _Open:
    def __init__(self, c):
        self.c = c

    def __getattr__(self, name):
        return getattr(self.c, name)

    def close(self):
        pass


@pytest.fixture
def conn(monkeypatch):
    c = ms.connect()
    monkeypatch.setattr(lane_gate, "shut", lambda conn, wanted, now=None: {})
    yield c
    c.close()


def _put(c, name, lane, outcome="queued", size_gib=4, library=""):
    ms.record(c, ms.Seen(name=name, source="test", url="", why="", relevance=0, kind="candidate",
                         registry=ms.HUGGINGFACE, lane=lane, resolved=name))
    ms.decide(c, name, "queued", tier=ms.INSPECT, detail="fits")
    c.execute("UPDATE proposals SET size_bytes = ?, library = ? WHERE name = ?", (size_gib * GIB, library, name))
    if outcome != "queued":
        ms.decide(c, name, outcome, tier=ms.SCREEN, detail="passed")


def _ready(name, lane):
    return {"name": name, "lane": lane, "modality": lane, "state": "ready", "resolved": name}


def _pause(c, lane, name):
    paused.save(c, lane=lane, inc_spec="inc", spec=name, proposal=name, out=f"/o/{name}", ident={}, plan={}, done=1,
                total=9, looks=[])


def _job(c, lane, name, state="running"):
    argv = ["uv", "run", "soh", "adopt", "--lane", lane, "--challenger", name, "--repeat", "3"]
    c.execute("INSERT INTO jobs (title, argv, state, requested_by, created_at, machine_id) VALUES (?,?,?,?,?,?)",
              (f"adopt {name}", json.dumps(argv), state, "test", time.time(), ms.remember_machine(c)))


def test_wip_counts_a_lanes_screened_paused_and_running_measures_once_each(conn):
    _put(conn, "org/a1", "code", "screened")
    _put(conn, "org/a2", "code", "screened")
    _put(conn, "org/a3", "code")
    _put(conn, "org/b1", "svg", "screened")
    _pause(conn, "svg", "org/b1")
    _pause(conn, "svg", "org/b2")
    _job(conn, "svg", "org/b3")
    _job(conn, "svg", "org/b3")
    _job(conn, "tts", "org/c1", state="done")
    got = {lane: sorted(names) for lane, names in wip.used(conn).items()}
    assert got == {"code": ["org/a1", "org/a2"], "svg": ["org/b1", "org/b2", "org/b3"]}


def test_a_lane_at_its_limit_pulls_nothing_and_a_lane_below_it_pulls_its_head(conn, monkeypatch):
    monkeypatch.setattr(wip, "LIMIT", 2)
    _put(conn, "org/a1", "code", "screened")
    _put(conn, "org/a2", "code", "screened")
    _put(conn, "org/b1", "svg")
    got = wip.pull(conn, [_ready("org/a3", "code"), _ready("org/b1", "svg"), _ready("org/a4", "code")])
    assert [r["name"] for r in got] == ["org/b1"]


def test_a_lane_with_room_for_one_pulls_one_in_rank_order(conn, monkeypatch):
    monkeypatch.setattr(wip, "LIMIT", 2)
    _put(conn, "org/a1", "code", "screened")
    rows = [_ready("org/a2", "code"), _ready("org/b1", "svg"), _ready("org/a3", "code"), _ready("org/b2", "svg")]
    assert [r["name"] for r in wip.pull(conn, rows)] == ["org/a2", "org/b1", "org/b2"]


def test_the_screen_step_screens_only_the_lane_below_its_limit(conn, monkeypatch):
    monkeypatch.setattr(wip, "LIMIT", 2)
    monkeypatch.setattr(ms, "connect", lambda *a, **k: _Open(conn))
    _put(conn, "org/a1", "code", "screened")
    _put(conn, "org/a2", "code", "screened")
    _put(conn, "org/a3", "code")
    _put(conn, "org/b1", "svg")
    full = [_ready("org/a3", "code"), _ready("org/b1", "svg")]
    assert [r["name"] for r in screen_cmd._todo(full, conn)] == ["org/b1"]


def test_the_screen_share_is_what_the_pulls_need_capped_and_the_rest_goes_to_measure(monkeypatch):
    now = 1000.0
    cap = now + 3 * 3600
    assert wip.share_until(cap, now, 1, 600.0) == now + 1200.0
    assert wip.share_until(cap, now, 100, 600.0) == cap
    assert wip.share_until(None, now, 1, 600.0) is None
    assert wip.share_until(cap, now, 0, 600.0) == now + 600.0


def test_a_candidate_needing_a_missing_runner_never_enters_the_ranked_list(conn):
    _put(conn, "org/no-runner", "image", library="comfyui")
    _put(conn, "org/fine", "code")
    names = [r["name"] for r in report.ranked(conn)]
    assert "org/no-runner" not in names and "org/fine" in names
    held = prefilter.split(conn, ms.judgeable(conn, limit=100))[1]
    assert held["org/no-runner"][0] == "runner" and "runner" in held["org/no-runner"][1]


def test_a_dependency_over_the_download_cap_keeps_the_candidate_out(conn, monkeypatch):
    _put(conn, "org/needs-big", "code")
    _put(conn, "org/base", "code", size_gib=67)
    monkeypatch.setattr(fetching, "requires", lambda name, c=None: ["org/base"] if name == "org/needs-big" else [])
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    kept, held = prefilter.split(conn, ms.judgeable(conn, limit=100))
    assert "org/needs-big" in held and held["org/needs-big"][0] == "dependency"
    assert "67.0 GiB is over the 60 GiB cap" in held["org/needs-big"][1]
    assert "org/needs-big" not in [r["name"] for r in kept]


def test_a_load_over_what_a_screen_window_can_free_keeps_the_candidate_out(conn, monkeypatch):
    from harness import memory
    _put(conn, "org/huge", "code", size_gib=90)
    _put(conn, "org/small", "code", size_gib=4)
    monkeypatch.setattr(memory, "standing_gb", lambda: 30.0)
    monkeypatch.setattr(memory, "released_gb", lambda: 50.0)
    held = prefilter.split(conn, ms.judgeable(conn, limit=100))[1]
    assert held["org/huge"][0] == "window" and "org/small" not in held


def test_a_demoted_family_is_kept_out_and_says_so(conn, monkeypatch):
    _put(conn, "org/lost-7b", "code")
    _put(conn, "org/other-7b", "code")

    class Standing:
        def demotion(self, row, lane):
            return (family.DEMOTION, "2 of the lost family lost") if row["name"] == "org/lost-7b" else (0.0, "")
    held = prefilter.split(conn, ms.judgeable(conn, limit=100), standing=Standing())[1]
    assert held["org/lost-7b"][0] == "family" and "org/other-7b" not in held


def test_a_refetch_the_budget_refuses_keeps_the_candidate_out(conn, monkeypatch):
    _put(conn, "org/again", "code")
    monkeypatch.setattr(refetch, "holds", lambda c, repo, via, owner="", now=None: "downloaded 1.0 h ago" if repo == "org/again" else "")
    held = prefilter.split(conn, ms.judgeable(conn, limit=100))[1]
    assert held["org/again"][0] == "refetch"


def test_a_screen_run_records_the_prefilter_reason_and_the_funnel_explains_it(conn, monkeypatch):
    monkeypatch.setattr(ms, "connect", lambda *a, **k: _Open(conn))
    _put(conn, "org/no-runner", "image", library="comfyui")
    screen_cmd._record_prefilter("")
    row = conn.execute("SELECT p.state, v.tier, v.detail FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                       "WHERE p.name = 'org/no-runner'").fetchone()
    assert row["state"] == "queued" and row["tier"] == "fetch" and row["detail"].startswith("prefilter:")
    from harness import funnel
    got = {r["name"]: r for r in funnel.proposals(conn)}["org/no-runner"]
    assert got["reason"] == "prefilter" and got["why"].startswith("runner:") and got["stage"] != "ranked"


def test_the_flow_panel_shows_each_open_lanes_wip_out_of_its_limit(conn, monkeypatch):
    monkeypatch.setattr(wip, "LIMIT", 2)
    _put(conn, "org/a1", "code", "screened")
    _put(conn, "org/a2", "code", "screened")
    _put(conn, "org/b1", "svg", "screened")
    flow = discovery_flow.gather(conn, time.time())
    got = {w["lane"]: (w["used"], w["limit"]) for w in flow["wip"]}
    assert got["code"] == (2, 2) and got["svg"] == (1, 2)
    html = sv._flow({**flow, "as_of": time.time()}, time.time(), [])
    assert "data-wip='code'" in html and "2 of 2" in html and "1 of 2" in html


def test_measure_wip_is_a_registered_knob():
    from harness import knobs
    assert knobs.KNOBS["measure_wip"].default() == wip.LIMIT == 2
