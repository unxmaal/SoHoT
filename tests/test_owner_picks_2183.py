"""#2183: a perceptual lane's holdout win waits for the owner's blind A/B picks; adoption follows them."""
from __future__ import annotations

import json
import random
import time
import types

import pytest

from harness import adopt, lanes, needs_you, owner_actions as oa, owner_picks, reasons, runs, test_weights, wip
from harness import memory_store as ms
from harness import status_buttons as sb
from harness import status_view as sv

INC, CHAL = "mflux:acme-secret-inc", "mflux:acme-secret-chal"
INC_KEY, CHAL_KEY = "mflux_acme-secret-inc", "mflux_acme-secret-chal"
PHONE = "203.0.113.7"


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _proposal(c, name, lane):
    ms.record(c, ms.Seen(name=name, source="test", url="", why="", relevance=0, kind="candidate",
                         registry=ms.HUGGINGFACE, lane=lane, resolved=name))
    ms.decide(c, name, "queued", tier=ms.INSPECT, detail="fits")
    ms.decide(c, name, "screened", tier=ms.SCREEN, detail="passed")


def _run(c, tmp_path, lane, cases=8, suffix=".png"):
    run = tmp_path / f"20261127-000000-{lane}"
    run.mkdir(exist_ok=True)
    rows = []
    for i in range(cases):
        for key in (INC_KEY, CHAL_KEY):
            f = run / f"{key}--case{i}{suffix}"
            f.write_bytes(b"x")
            rows.append({"case_id": f"case{i}", "candidate": key, "passed": True, "artifact_path": str(f)})
    return runs.record(c, run, {"receipt": {"modality": lane}, "rows": rows})


def _win(lane="image", **kw):
    return adopt.Verdict(lane, INC_KEY, CHAL_KEY, True, "won the holdout", **kw)


def _served(c, lane="image"):
    return adopt.adopted(c).get(lane)


def _stand(c, tmp_path, lane="image", name="acme/chal-secret"):
    _proposal(c, name, lane)
    return _run(c, tmp_path, lane), name


def _pick_all(c, pid, want):
    """Pick every pair so the challenger gets `want[i]` ('chal', 'inc' or 'none'), reading the side from the stored pair."""
    it = owner_picks.get(c, pid)
    said = ""
    for i, p in enumerate(it["pairs"]):
        w = want[i]
        side = "none" if w == "none" else ("left" if p["left_is"] == w else "right")
        _, said = owner_picks.pick(c, pid, i, side)
    return said


def _item(c):
    (it,) = owner_picks.waiting(c)
    return it


def test_a_planted_challenger_waits_for_picks_then_adopts(conn, tmp_path):
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    assert _served(conn) is None
    it = _item(conn)
    assert len(it["pairs"]) == owner_picks.PAIRS and it["lane"] == "image"
    held = conn.execute("SELECT outcome, failure_class FROM verdicts WHERE id = ?", (it["verdict_id"],)).fetchone()
    assert held["failure_class"] == reasons.AWAITING_OWNER and held["outcome"] == "declined"
    for i in range(owner_picks.PAIRS - 1):
        _, said = owner_picks.pick(conn, it["id"], i, "none")
        assert "left" in said and _served(conn) is None
    said = _pick_all(conn, it["id"], ["chal"] * owner_picks.PAIRS)
    assert said.startswith("ADOPTED") and _served(conn) == name
    assert owner_picks.waiting(conn) == []


def test_a_decline_follows_the_picks_and_records_them(conn, tmp_path):
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    pid = _item(conn)["id"]
    said = _pick_all(conn, pid, ["inc", "chal", "inc", "inc", "none", "chal"])
    assert said.startswith("declined") and _served(conn) is None
    v = conn.execute("SELECT outcome, reason, power FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()
    assert (v["outcome"], v["reason"]) == ("declined", reasons.OWNER_PREFERENCE)
    got = json.loads(v["power"])[owner_picks.PICKED]
    assert (got["chal"], got["inc"], got["none"]) == (2, 3, 1) and len(got["pairs"]) == 6


@pytest.mark.parametrize("chal,inc,none,adopts", [(4, 2, 0, True), (4, 0, 2, True), (3, 0, 3, False), (3, 2, 1, False),
                                                  (6, 0, 0, True), (2, 4, 0, False)])
def test_the_challenger_needs_a_clear_majority_of_the_decided_pairs(chal, inc, none, adopts):
    pairs = [{"pick": "left", "left_is": "chal"}] * chal + [{"pick": "left", "left_is": "inc"}] * inc + [{"pick": "none", "left_is": "inc"}] * none
    assert owner_picks.preferred(pairs) is adopts


def test_enough_wins_still_need_to_beat_the_incumbents_wins():
    pairs = [{"pick": "left", "left_is": "chal"}] * 3 + [{"pick": "left", "left_is": "inc"}] * 3
    assert owner_picks.preferred(pairs, needed=3) is False


def test_a_tie_never_counts_for_the_challenger(conn, tmp_path):
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    said = _pick_all(conn, _item(conn)["id"], ["chal", "chal", "chal", "none", "none", "none"])
    assert said.startswith("declined") and _served(conn) is None


def test_a_code_lane_win_adopts_with_no_owner_step(conn, tmp_path):
    run_id, name = _stand(conn, tmp_path, lane="code", name="acme/coder")
    adopt.record(conn, adopt.Verdict("code", INC_KEY, CHAL_KEY, True, "won the holdout"), spec=name, run_id=run_id)
    assert _served(conn, "code") == name and owner_picks.waiting(conn) == []


def test_a_perceptual_win_with_no_stored_output_is_not_held_for_ever(conn, tmp_path):
    _proposal(conn, "acme/chal-secret", "image")
    adopt.record(conn, _win(), spec="acme/chal-secret", run_id=None)
    assert _served(conn) is None and owner_picks.waiting(conn) == []
    v = conn.execute("SELECT failure_class FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()
    assert v["failure_class"] == reasons.HARNESS_ERROR


@pytest.mark.parametrize("lane", ["image", "music", "video", "tts"])
def test_the_four_perceptual_lanes_hold(lane):
    assert lanes.perceptual(lane) and not lanes.perceptual("code")


def test_left_and_right_are_not_fixed_by_role_over_many_seeds(conn, tmp_path):
    run_id, _ = _stand(conn, tmp_path)
    names = {INC_KEY: "inc", CHAL_KEY: "chal"}
    firsts, every = [], []
    for seed in range(300):
        got = owner_picks.pairs_for(conn, [run_id], names, 6, random.Random(seed))
        firsts.append(got[0]["left_is"])
        every += [p["left_is"] for p in got]
    assert 0.4 < every.count("chal") / len(every) < 0.6
    assert 0.4 < firsts.count("chal") / len(firsts) < 0.6
    assert {p["left_is"] for p in owner_picks.pairs_for(conn, [run_id], names, 8, random.Random(1))} == {"inc", "chal"}


def _gathered(conn):
    return {"generated": time.time(), "stops": {"picks": owner_picks.read(conn)}, "needs_you": []}


def test_the_rendered_item_names_no_model_and_shows_the_media(conn, tmp_path):
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    r = _gathered(conn)
    r["needs_you"] = needs_you._picks(r)
    (c,) = [c for c in r["needs_you"] if c["key"].startswith("picks-")]
    tok = oa.token(PHONE, {"id": PHONE, "name": PHONE})
    body = sv._need(c, time.time(), tok) + json.dumps(r)
    for secret in ("acme", "secret", "mflux", "chal-", "inc-", name, "left_is", ".png"):
        assert secret not in body
    assert "<img" in body and body.count("Left is better") == owner_picks.PAIRS and "No preference" in body
    assert f"status/pick-media/{c['key'].removeprefix('picks-')}/0/left" in body


def test_audio_and_video_items_play_in_their_own_elements(conn, tmp_path):
    _proposal(conn, "acme/chal-secret", "music")
    run_id = _run(conn, tmp_path, "music", suffix=".wav")
    adopt.record(conn, _win("music"), spec="acme/chal-secret", run_id=run_id)
    c = needs_you._picks({"stops": {"picks": owner_picks.read(conn)}})[0]
    assert "<audio" in sb.picks(c, "tok") and "<img" not in sb.picks(c, "tok")
    assert owner_picks.kind_of("a.mp4") == "video" and owner_picks.kind_of("a.txt") == ""


def test_the_status_section_has_no_spec_in_its_json(conn, tmp_path):
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    text = json.dumps(owner_picks.read(conn))
    assert "acme" not in text and "left_is" not in text and ".png" not in text


def test_media_is_served_only_for_a_waiting_pair_and_a_named_side(conn, tmp_path):
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    pid = _item(conn)["id"]
    path, mime = owner_picks.media(conn, pid, 0, "left")
    assert mime == "image/png" and path.is_file()
    assert owner_picks.media(conn, pid, 99, "left") is None and owner_picks.media(conn, pid, 0, "../x") is None
    assert owner_picks.media(conn, pid + 1, 0, "left") is None
    _pick_all(conn, pid, ["inc"] * 6)
    assert owner_picks.media(conn, pid, 0, "left") is None


def test_a_waiting_win_takes_its_lanes_whole_wip_room_and_pins_its_weights(conn, tmp_path, monkeypatch):
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    assert wip.used(conn)["image"] == [name]
    rows = [{"name": f"n{i}", "lane": "image", "modality": "image"} for i in range(2)] + [{"name": "c", "lane": "code", "modality": "code"}]
    assert [r["name"] for r in wip.pull(conn, rows)] == ["c"]
    assert owner_picks.holds_weights(conn, name)
    swept = []
    monkeypatch.setattr("harness.disk.sweep", lambda **kw: swept.append(kw))
    test_weights.release(name)
    assert swept == []
    _pick_all(conn, _item(conn)["id"], ["inc"] * 6)
    assert swept and swept[0]["names"] == [name]
    assert wip.used(conn).get("image") is None


def _press(arg, r, run=None):
    ran = []
    form = {"token": oa.token(PHONE, {"id": PHONE, "name": PHONE}), "action": "pick", "arg": arg}
    code, text = oa.press(PHONE, {}, form, r, home=None, run=run or (lambda cmd, **kw: ran.append(cmd) or types.SimpleNamespace(
        returncode=0, stdout="picked", stderr="")))
    return code, text, ran


def test_a_pick_is_one_press_of_a_listed_choice_and_never_a_free_argument(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(oa, "audit", lambda *a, **k: None)
    monkeypatch.setattr("harness.status_page.forget", lambda: None)
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    r = {"stops": {"picks": owner_picks.read(conn)}}
    pid = _item(conn)["id"]
    code, text, ran = _press(f"{pid}:0:left", r)
    assert code == 200 and ran and ran[0][-5:] == ["owner-picks", "pick", str(pid), "0", "left"]
    for bad in (f"{pid}:0:both", f"{pid + 1}:0:left", f"{pid}:9:left", "x; rm"):
        assert _press(bad, r)[0] == 400
    assert "value='pick'" not in oa.panel(r, "tok") and "value='queue_resume'" in oa.panel(r, "tok")


def test_the_pick_command_records_and_refuses_a_bad_pair(conn, tmp_path, capsys):
    from harness import cli
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    pid = _item(conn)["id"]
    assert cli.main(["owner-picks", "pick", str(pid), "0", "none"]) == 0
    assert "5 left" in capsys.readouterr().out
    assert cli.main(["owner-picks", "pick", str(pid), "9", "none"]) == 1
    assert cli.main(["owner-picks", "list"]) == 0 and f"item {pid}" in capsys.readouterr().out


def test_the_status_page_shows_the_item_in_the_band_and_serves_its_media(conn, tmp_path, monkeypatch):
    from tests import test_status_page_2075 as base
    srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")
    from starlette.testclient import TestClient
    from harness import status_page as sp
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    r = base._gather(tmp_path)
    assert any(c["key"].startswith("picks-") for c in r["needs_you"]) and r["banner"]
    monkeypatch.setattr(sp, "cached", lambda: r)
    client = TestClient(srv.SERVER.streamable_http_app(transport_security=srv.transport_security("0.0.0.0", 8899), host="0.0.0.0"))
    page = client.get("/status", headers={"host": "localhost:8899"}).text
    assert "Pick the better image output" in page and page.count("<img") == owner_picks.PAIRS * 2 and "Needs you" in page
    item = page[page.index("<article class='need' id='need-picks-"):].split("</article>")[0]
    assert item.count("Left is better") == owner_picks.PAIRS and "acme" not in item and "secret" not in item
    pid = _item(conn)["id"]
    got = client.get(f"/status/pick-media/{pid}/0/left", headers={"host": "localhost:8899"})
    assert got.status_code == 200 and got.headers["content-type"] == "image/png" and got.content == b"x"
    for url in (f"/status/pick-media/{pid}/9/left", f"/status/pick-media/{pid}/0/up", "/status/pick-media/x/0/left"):
        assert client.get(url, headers={"host": "localhost:8899"}).status_code == 404


def test_a_waiting_challengers_weights_are_a_disk_keeper(conn, tmp_path):
    from harness import disk
    run_id, name = _stand(conn, tmp_path)
    adopt.record(conn, _win(), spec=name, run_id=run_id)
    assert name.lower() in disk.keepers(conn, gateway_files={}, typed={}, adopted={}).repos
    _pick_all(conn, _item(conn)["id"], ["inc"] * 6)
    assert name.lower() not in disk.keepers(conn, gateway_files={}, typed={}, adopted={}).repos
