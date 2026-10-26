"""A lane's findings as one versioned document, over the CLI, the MCP and the reports branch. #1200."""
import base64
import json

import pytest

from harness import candidates, cli, lane_feed, publish, runs
from harness import memory_store as ms

T0 = 1_790_000_000.0
WINNER, LOSER = "org/vid-winner", "org/vid-loser"
METRICS = {"motion": 0.42, "adherence": 0.8}
# privacy-ok: deliberate fixtures, the things a published file must never carry.
USER, HOST = "patq", "patq-tower"


def _here_env() -> dict:
    me = ms.this_machine()
    return {k: me.get(k) for k in ("hw_model", "os", "arch", "host", "memory_gb")}


def _propose(conn, name):
    ms.record(conn, ms.Seen(name=name, source="t", url="", why="", relevance=0, kind="candidate",
                            registry=ms.HUGGINGFACE, lane="video", resolved=name))
    return candidates.ensure(conn, name, proposal=name, lane="video")


def _video_run(conn):
    rows = [{"case_id": f"c{i}", "candidate": cand, "passed": p, "seconds": 40.0 + i,
             "peak_kb": 30 * 1024 ** 2, "metrics": METRICS}
            for cand, passed in ((WINNER, [1, 1, 1]), (LOSER, [1, 0, 0])) for i, p in enumerate(passed)]
    runs.record(conn, "runs/video-1", {"generated": "2026-10-20T10:00:00",
                                        "receipt": {"modality": "video", "tier": "measure"},
                                        "environment": _here_env(), "rows": rows})
    return conn.execute("SELECT id FROM runs WHERE path = 'runs/video-1'").fetchone()["id"]


def plant(conn, *, detail=""):
    """An adoption at T0+10, a rejection at T0+20 and a settled knob decision at T0+30 on video."""
    ms.remember_machine(conn)
    mid = ms.machine_row(conn)
    run_id = _video_run(conn)
    win, lose = _propose(conn, WINNER), _propose(conn, LOSER)
    vid = ms.decide(conn, WINNER, "measured", tier="adopt", detail="video: won 3 of 3 against h3",
                    candidate_id=win, run_id=run_id, reason="candidate", at=T0 + 10)
    conn.execute("INSERT INTO adoptions (lane, candidate_id, run_id, verdict_id, machine_id, how, adopted_at) "
                 "VALUES ('video', ?, ?, ?, ?, 'measured', ?)", (win, run_id, vid, mid, T0 + 10))
    ms.decide(conn, LOSER, "declined", tier="adopt", candidate_id=lose, run_id=run_id, reason="candidate",
              detail=detail or "video: lost to org/vid-winner on 2 of 3 cases", at=T0 + 20)
    conn.execute("INSERT INTO knob_sweeps (knob, lane, spec, candidate_id, machine_id, queued_at, settled_at, "
                 "outcome, chosen, detail) VALUES ('frames', 'video', ?, ?, ?, ?, ?, 'chosen', '22', ?)",
                 (WINNER, win, mid, T0 + 25, T0 + 30, "22 frames tied with 33 at a third less time"))
    conn.commit()


@pytest.fixture
def store():
    conn = ms.connect()
    plant(conn)
    yield conn
    conn.close()


def _ro():
    return lane_feed.open_store()


def test_an_adoption_a_rejection_and_a_knob_decision_appear_with_their_reasons(store):
    doc = lane_feed.lane_feed(_ro(), "video", now=T0 + 40)
    assert doc["served"]["serves"] == WINNER and doc["served"]["adopted"] is True
    assert doc["served"]["adopted_how"] == "measured" and doc["served"]["adopted_at"].startswith("2026-")
    by = {c["candidate"]: c for c in doc["candidates"]}
    assert by[WINNER]["status"] == "adopted" and by[WINNER]["serves"] is True
    assert by[LOSER]["status"] == "rejected" and by[LOSER]["reason"] == "candidate"
    assert "lost to org/vid-winner" in by[LOSER]["detail"]
    exam = by[LOSER]["exam"]
    assert exam["cases"] == 3 and exam["passed"] == 1 and exam["peak_gb"] == 30.0
    assert exam["metrics"] == METRICS and exam["median_s"] == 41.0
    assert doc["lane"]["params"]["width"] and doc["lane"]["params"]["frames"]
    [knob] = doc["knobs"]
    assert (knob["knob"], knob["outcome"], knob["chosen"]) == ("frames", "chosen", 22)
    assert "tied with 33" in knob["detail"]
    kinds = [(e["kind"], e["candidate"]) for e in doc["events"]]
    assert kinds == [("adoption", WINNER), ("verdict", LOSER), ("knob", WINNER)]
    assert doc["events"][0]["reason"] == "candidate" and "won 3 of 3" in doc["events"][0]["detail"]
    assert doc["events"][1]["outcome"] == "declined" and doc["events"][2]["chosen"] == 22


def test_since_the_first_events_id_returns_exactly_the_later_two(store):
    first = lane_feed.lane_feed(_ro(), "video")["events"]
    got = lane_feed.lane_feed(_ro(), "video", since=first[0]["id"])
    assert [e["id"] for e in got["events"]] == [first[1]["id"], first[2]["id"]]
    assert first[0]["id"] < first[1]["id"] < first[2]["id"]
    assert got["cursor"] == first[2]["id"]
    assert lane_feed.lane_feed(_ro(), "video", since=got["cursor"])["events"] == []


def test_a_row_written_later_gets_a_higher_id_than_every_id_already_handed_out(store):
    cursor = lane_feed.lane_feed(_ro(), "video")["cursor"]
    ms.decide(store, LOSER, "queued", tier="screen", reopen="retest", reopen_why="a new runtime", at=T0 + 31)
    store.commit()
    [new] = lane_feed.lane_feed(_ro(), "video", since=cursor)["events"]
    assert (new["kind"], new["candidate"]) == ("screen", LOSER) and new["id"] > cursor


def test_the_cli_the_mcp_resource_and_the_published_file_are_one_document(store, capsys, monkeypatch):
    server = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group")
    import anyio
    monkeypatch.setattr(lane_feed, "_now", lambda: T0 + 40)
    assert cli.main(["lane-feed", "video", "--json"]) == 0
    from_cli = json.loads(capsys.readouterr().out)
    [content] = anyio.run(lambda: server.SERVER.read_resource("soh://lanes/video"))
    from_resource = json.loads(content.content)
    tool = anyio.run(lambda: server.SERVER.call_tool("lane_feed", {"lane": "video"}))
    gh = FakeGh()
    publish.publish_lanes({"video": lane_feed.lane_feed(store, "video")}, "box", repo="o/r", gh=gh)
    [(args, body)] = [(a, b) for a, b in gh.calls if "PUT" in a]
    assert args[0] == "repos/o/r/contents/lanes/box/video.json"
    from_file = json.loads(base64.b64decode(body["content"]))
    assert from_cli == from_resource == from_file
    assert tool.structured_content == from_cli
    assert from_cli["events"] and from_cli["candidates"]


def test_an_unknown_lane_is_an_error_on_every_surface(store, capsys):
    assert cli.main(["lane-feed", "no-such-lane", "--json"]) == 1
    assert "no lane named" in json.loads(capsys.readouterr().out)["error"]
    with pytest.raises(lane_feed.UnknownLane):
        lane_feed.lane_feed(store, "no-such-lane")


def test_a_lane_with_no_runs_is_a_valid_document_with_empty_lists(store):
    doc = lane_feed.lane_feed(_ro(), "music")
    assert doc["schema_version"] == lane_feed.SCHEMA_VERSION
    assert (doc["candidates"], doc["exams"], doc["knobs"], doc["events"]) == ([], [], [], [])
    assert doc["lane"]["name"] == "music" and doc["cursor"] == 0
    assert doc["served"]["adopted"] is False
    empty = ms.connect(ms.db_path().with_name("empty.db"))
    assert lane_feed.lane_feed(empty, "video")["events"] == []


def test_the_feed_writes_nothing_to_the_store(store):
    before = store.total_changes
    ro = _ro()
    lane_feed.lane_feed(ro, "video")
    assert ro.total_changes == 0 and store.total_changes == before


def test_every_funnel_stage_has_a_status_a_consumer_reads():
    from harness import funnel
    assert set(lane_feed.STATUS) == set(funnel.STAGES)
    assert set(lane_feed.STATUS.values()) == set(lane_feed.STATUSES)


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/lane_feed.py:_lane_candidates")
def test_a_candidate_no_proposal_names_reads_its_newest_decision_not_its_newest_row():
    conn = ms.connect()
    cid = candidates.ensure(conn, "org/typed-video", lane="video")
    for outcome, at in (("measured", T0 + 50), ("declined", T0 + 5)):
        conn.execute("INSERT INTO verdicts (candidate_id, outcome, tier, detail, decided_at, reason) "
                     "VALUES (?, ?, 'measure', '', ?, 'candidate')", (cid, outcome, at))
    conn.commit()
    [got] = [c for c in lane_feed.lane_feed(conn, "video")["candidates"] if c["candidate"] == "org/typed-video"]
    assert (got["outcome"], got["status"]) == ("measured", "measured")


# --- the reports branch and the privacy scan --------------------------------

class FakeGh:
    def __init__(self, existing=None):
        self.calls, self.existing = [], existing or {}

    def __call__(self, args, body=None):
        self.calls.append((args, body))
        url = args[0]
        if "/contents/" in url and "-X" not in args:
            path = url.split("/contents/", 1)[1].split("?", 1)[0]
            if path not in self.existing:
                raise publish.GhError("gh: Not Found (HTTP 404)")
            return {"sha": "old", "content": base64.b64encode(self.existing[path].encode()).decode()}
        return {"sha": f"sha{len(self.calls)}"}


@pytest.fixture
def private(monkeypatch):
    monkeypatch.setattr(publish, "_local_names", lambda: [USER, HOST])


def test_a_lane_file_carrying_a_hostname_is_refused_and_the_rest_still_publish(private):
    conn = ms.connect()
    plant(conn, detail=f"lost on {HOST} reading /Users/{USER}/models/vid.safetensors")  # privacy-ok
    raw = f"/Users/{USER}/models/vid.safetensors"  # privacy-ok
    assert publish.findings({"detail": raw}), "the path pattern must fire on an unscrubbed path"
    docs = {lane: lane_feed.lane_feed(conn, lane) for lane in ("video", "music")}
    text = json.dumps(docs["video"])
    assert "/Users/" not in text and "vid.safetensors" in text
    assert publish.findings(docs["video"]) and not publish.findings(docs["music"])
    with pytest.raises(publish.ExportRefused):
        publish.checked(docs["video"])
    gh = FakeGh()
    got = publish.publish_lanes(docs, "box", repo="o/r", gh=gh)
    assert list(got["refused"]) == ["video"] and got["written"] == ["lanes/box/music.json"]
    sent = json.dumps([b for _, b in gh.calls])
    assert HOST not in sent and base64.b64encode(HOST.encode()).decode()[:6] not in sent


def test_the_same_document_is_not_committed_again(store, private):
    docs = {"video": lane_feed.lane_feed(store, "video", now=T0 + 40)}
    old = json.dumps(lane_feed.lane_feed(store, "video", now=T0 + 99), indent=1, sort_keys=True)
    gh = FakeGh(existing={"lanes/box/video.json": old})
    got = publish.publish_lanes(docs, "box", repo="o/r", gh=gh)
    assert got["unchanged"] == ["lanes/box/video.json"] and not [a for a, _ in gh.calls if "PUT" in a]


def test_publish_here_writes_the_machine_file_and_the_lane_files_then_builds_once(store, private):
    gh = FakeGh()
    said = publish.publish_here(store, gh=gh, repo="o/r")
    puts = [a[0] for a, _ in gh.calls if "PUT" in a]
    slug = publish.export(store)["machine"]["slug"]
    assert puts[0] == f"repos/o/r/contents/machines/{slug}.json"
    assert f"repos/o/r/contents/lanes/{slug}/video.json" in puts
    assert sum("dispatches" in a[0] for a, _ in gh.calls) == 1 and "dispatches" in gh.calls[-1][0][0]
    assert "lane file(s) written" in said


# --- the shape is pinned to its version -------------------------------------

def _shape(value):
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return ""


#: Recorded per SCHEMA_VERSION. A change here without a new version is a breaking change for Kubrick.
SHAPES = {1: "ba68fa0b", 2: "f899176d"}


def test_schema_version_is_pinned_to_the_documents_shape(store):
    import hashlib
    doc = lane_feed.lane_feed(store, "video")
    keys = {"schema_version", "generated_at", "lane", "machine", "served", "candidates", "exams", "knobs",
            "since", "cursor", "events"}
    assert set(doc) == keys
    shape = json.dumps({k: _shape(doc[k]) for k in ("lane", "served", "candidates", "knobs", "events")}
                       | {"exams": _shape(doc["exams"][0]["rows"][0])}, sort_keys=True)
    fingerprint = hashlib.sha256(shape.encode()).hexdigest()[:8]
    assert max(SHAPES) == lane_feed.SCHEMA_VERSION
    assert SHAPES[lane_feed.SCHEMA_VERSION] == fingerprint, (fingerprint, shape)
