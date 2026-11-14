"""#2011: discovery must not fill the weights volume, keep declined weights, or block deploys without saying so."""
from __future__ import annotations

import argparse

import pytest

from harness import deploy, disk, downloads, env, fetching, memory
from harness import memory_store as ms
from harness.commands import screen as screen_cmd
from tests.test_env_sh import run_env
from tests.test_harness_disk import DAY, NOW, inv, make_repo, verdict, world  # noqa: F401
from tests.test_harness_fetching_budget import _seed, _sizes, store  # noqa: F401

GIB = fetching.GIB


def _fetched(conn, name, path, *, gib=0.0, at=NOW - 10 * DAY):
    rid = downloads.record(conn, name, downloads.HUB, path, proposal=name, at=at)["id"]
    conn.execute("UPDATE downloads SET bytes = ?, finished_at = ? WHERE id = ?", (int(gib * GIB), at, rid))
    conn.commit()
    return rid


def _queued_for_screen(conn, name, lane="code"):
    _seed(conn, name, 1.0, lane=lane)
    ms.decide(conn, name, "queued", tier="screen", detail="waits for memory")


# ---- 1. the screen backlog cap and the deadline -----------------------------------------------------

def test_fetch_is_skipped_with_its_reason_while_the_screen_backlog_is_over_the_cap(store, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "SCREEN_BACKLOG", 100 * GIB)
    _queued_for_screen(store, "org/waiting")
    _fetched(store, "org/waiting", tmp_path / "models--org--waiting", gib=120)
    _seed(store, "org/next", 5.0)
    room, why = fetching.backlog_room(store)
    assert room == 0 and "120.0 GiB" in why and "100 GiB backlog cap" in why
    called = []
    monkeypatch.setattr(fetching, "run", lambda *a, **k: called.append(k) or [])
    a = argparse.Namespace(replay=None, lane="", run=True, limit=5, budget_gib=80, hold_router=True, until=None,
                           limit_knob=None, budget_knob=None, json=False)
    assert screen_cmd.cmd_fetch(a) == 0
    assert called == []


def test_a_backlog_under_the_cap_fetches_only_what_fits_the_room_left(store, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "SCREEN_BACKLOG", 100 * GIB)
    _queued_for_screen(store, "org/waiting")
    _fetched(store, "org/waiting", tmp_path / "models--org--waiting", gib=90)
    _seed(store, "org/big", 15.0)
    _seed(store, "org/small", 5.0)
    room, why = fetching.backlog_room(store)
    assert (room, why) == (10 * GIB, "")
    got = fetching.run(store, _sizes(store), limit=5, free=900 * GIB, room=room)
    assert [g["repo"] for g in got if g["ok"]] == ["org/small"]
    assert any(not g["ok"] and "backlog cap" in g["why"] for g in got if g["repo"] == "org/big")


def test_screened_or_declined_weights_are_not_the_screen_backlog(store, tmp_path, monkeypatch):
    _seed(store, "org/screened", 1.0)
    ms.decide(store, "org/screened", "screened", tier="screen")
    _fetched(store, "org/screened", tmp_path / "models--org--screened", gib=50)
    _queued_for_screen(store, "org/waits")
    _fetched(store, "org/waits", tmp_path / "models--org--waits", gib=7)
    assert disk.waiting_bytes(store) == 7 * GIB


def test_weights_queued_for_a_screen_past_the_deadline_go_and_the_fetch_takes_them_again(world):
    d = make_repo(world.hub, "org/stale")
    _queued_for_screen(world.conn, "org/stale")
    world.conn.execute("UPDATE downloads SET finished_at = ? WHERE repo = 'org/stale'",
                       (NOW - disk.QUEUED_DEADLINE_S - 3600,))
    world.conn.commit()
    got = disk.clean(inv(world), NOW, world.conn)
    assert [r["repo"] for r in got["evicted"]] == ["org/stale"]
    assert not d.exists()
    row = world.conn.execute("SELECT state, removed_by FROM downloads WHERE repo = 'org/stale'").fetchone()
    assert (row["state"], row["removed_by"]) == ("removed", disk.EVICTED)
    st = world.conn.execute("SELECT p.state, v.tier FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                            "WHERE p.name = 'org/stale'").fetchone()
    assert (st["state"], st["tier"]) == ("queued", "fetch")
    assert "org/stale" in [r["name"] for r in fetching.queued(world.conn)]


def test_fetched_weights_the_screen_can_never_load_beside_the_holds_go_now(world, monkeypatch):
    d = make_repo(world.hub, "org/27b", size=4096)
    _queued_for_screen(world.conn, "org/27b")
    world.conn.execute("UPDATE downloads SET finished_at = ? WHERE repo = 'org/27b'", (NOW - 3600,))
    world.conn.commit()
    monkeypatch.setattr(memory, "standing_gb", lambda: 2048 / GIB)
    got = disk.clean(inv(world), NOW, world.conn)
    assert [r["repo"] for r in got["evicted"]] == ["org/27b"] and not d.exists()
    detail = world.conn.execute("SELECT v.detail FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                                "WHERE p.name = 'org/27b'").fetchone()["detail"]
    assert memory.held_back(4096 / GIB) in detail


def test_weights_queued_inside_the_deadline_or_screened_stay(world):
    young = make_repo(world.hub, "org/young")
    _queued_for_screen(world.conn, "org/young")
    world.conn.execute("UPDATE downloads SET finished_at = ? WHERE repo = 'org/young'",
                       (NOW - disk.QUEUED_DEADLINE_S + 3600,))
    world.conn.commit()
    screened = make_repo(world.hub, "org/screened")
    _seed(world.conn, "org/screened", 1.0)
    ms.decide(world.conn, "org/screened", "screened", tier="screen")
    world.conn.execute("UPDATE downloads SET finished_at = ? WHERE repo = 'org/screened'", (NOW - 30 * DAY,))
    world.conn.commit()
    got = disk.clean(inv(world), NOW, world.conn)
    assert got["evicted"] == []
    assert young.exists() and screened.exists()


def test_inspect_fetch_and_screen_ask_one_sizing_question_beside_what_stays_held(store, monkeypatch):
    monkeypatch.setattr(memory, "standing_gb", lambda: 14.2)
    _seed(store, "org/27b", 51.7)
    _seed(store, "org/4b", 4.0)
    got = fetching.run(store, _sizes(store), limit=5, free=900 * GIB, held=memory.held_back)
    assert [g["repo"] for g in got if g["ok"]] == ["org/4b"]
    said = memory.held_back(51.7)
    assert "at most 14.2 GiB" in said and memory.held_back(14.0) == ""
    row = store.execute("SELECT p.state, v.tier, v.reason, v.detail FROM proposals p JOIN verdicts v "
                        "ON v.id = p.state_verdict_id WHERE p.name = 'org/27b'").fetchone()
    assert (row["state"], row["tier"], row["reason"]) == ("queued", "fetch", "limit") and said in row["detail"]
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: 51.7)
    assert memory.check_model("org/27b") == (False, said)


# ---- 2. the fetch leaves the deploy's floor ---------------------------------------------------------

def test_the_fetch_floor_is_the_deploys_floor_plus_the_margin_read_now(monkeypatch):
    monkeypatch.setenv("HF_MIN_FREE_GB", "20")
    assert fetching.disk_floor() == 20 * GIB + fetching.FLOOR_MARGIN
    monkeypatch.setenv("HF_MIN_FREE_GB", "45")
    assert fetching.disk_floor() == 45 * GIB + fetching.FLOOR_MARGIN


def _listing(sizes):
    return lambda repo: [{"rfilename": n, "size": int(g * GIB)} for n, g in sizes.items()]


def test_a_download_bigger_than_what_inspect_sized_is_refused_at_the_floor(store, monkeypatch):
    monkeypatch.setattr(fetching, "_patterns", lambda *a, **k: ())
    monkeypatch.setattr(fetching, "_chosen", lambda *a, **k: None)
    took = []
    snap = lambda repo_id, allow_patterns=None: took.append(repo_id) or "/x"  # noqa: E731
    files = _listing({f"q{i}.safetensors": 10.0 for i in range(5)})
    with pytest.raises(fetching.NoRoom, match="floor"):
        fetching._download("org/whole", snap, files, None, False, store, True, lane="image",
                           free=56 * GIB, floor=50 * GIB)
    assert took == []
    monkeypatch.setattr(downloads, "snapshot_dir", lambda p: p)
    monkeypatch.setattr(downloads, "landing", lambda *a, **k: __import__("contextlib").nullcontext())
    monkeypatch.setattr(downloads, "finish", lambda *a, **k: None)
    small = _listing({"model.safetensors": 4.0})
    fetching._download("org/small", snap, small, None, False, store, True, lane="image",
                       free=56 * GIB, floor=50 * GIB)
    assert took == ["org/small"]


def test_a_download_refused_for_room_stays_queued_as_a_fact_about_this_disk(store, monkeypatch):
    _seed(store, "org/whole", 6.7)

    def no_room(*a, **k):
        raise fetching.NoRoom("its download would take 50.5 GiB would leave under the 50 GiB floor")
    monkeypatch.setattr(fetching, "download", no_room)
    got = fetching.run(store, _sizes(store), limit=5, free=900 * GIB)
    assert [g["ok"] for g in got] == [False]
    row = store.execute("SELECT p.state, v.tier, v.reason FROM proposals p JOIN verdicts v "
                        "ON v.id = p.state_verdict_id WHERE p.name = 'org/whole'").fetchone()
    assert (row["state"], row["tier"], row["reason"]) == ("queued", "fetch", "machine")


# ---- 3. declined weights go after the verdict -------------------------------------------------------

def test_declined_weights_go_at_once_even_with_a_retest_pending(world):
    d = make_repo(world.hub, "org/declined")
    verdict(world.conn, "org/declined", "declined", tier="adopt", at=NOW - 60, retest=True)
    got = disk.clean(inv(world), NOW, world.conn)
    assert [r["repo"] for r in got["rejected"]] == ["org/declined"]
    assert not d.exists()


def test_declined_weights_another_proposal_still_waits_on_stay(world):
    _queued_for_screen(world.conn, "org/shared-q4")
    verdict(world.conn, "org/shared", "declined", tier="screen", at=NOW - 60)
    verdicts = disk.latest_verdicts(world.conn)
    e = disk.Entry("hub", "/x", "org/shared", repo="org/shared",
                   proposal_ids=[verdicts["org/shared"]["pid"], verdicts["org/shared-q4"]["pid"]])
    disk._classify(e, disk.Keepers(), verdicts)
    assert (e.group, e.why) == (disk.QUEUED, "queued at screen")
    e = disk.Entry("hub", "/x", "org/shared", repo="org/shared", proposal_ids=[verdicts["org/shared"]["pid"]])
    disk._classify(e, disk.Keepers(), verdicts)
    assert e.group == disk.REJECTED


def test_weights_the_harness_code_loads_are_kept_even_with_no_row(world):
    d = make_repo(world.hub, "google/owlv2-base-patch16-ensemble", recorded=False)
    e = next(e for e in inv(world).entries if e.path == str(d))
    assert e.unrecorded and e.group == disk.KEEP and "staging detector" in e.why
    assert "facebook/dinov2-small" in disk.owned() and "Cactus-Compute/needle3" in disk.owned()


def _aged(conn, repo, days):
    conn.execute("UPDATE downloads SET finished_at = ? WHERE repo = ?", (NOW - days * DAY, repo))
    conn.commit()


def test_weights_a_candidate_needs_beside_itself_follow_that_candidate(world):
    base = make_repo(world.hub, "Qwen/Qwen2.5-VL-3B-Instruct")
    make_repo(world.hub, "OmniSVG/OmniSVG1.1_4B")
    verdict(world.conn, "OmniSVG/OmniSVG1.1_4B", "declined", tier="screen", at=NOW - 60)
    tok = make_repo(world.hub, "Marvis-AI/marvis-tts-250m-v0.2")
    make_repo(world.hub, "Marvis-AI/marvis-tts-250m-v0.2-MLX-8bit")
    make_repo(world.hub, "Marvis-AI/marvis-tts-250m-v0.2-MLX-4bit")
    verdict(world.conn, "Marvis-AI/marvis-tts-250m-v0.2-MLX-4bit", "broken", tier="screen", at=NOW - 60)
    for user in ("Marvis-AI/marvis-tts-250m-v0.2-MLX-8bit", "Marvis-AI/marvis-tts-250m-v0.2-MLX-4bit"):
        world.conn.execute("UPDATE downloads SET requires = ? WHERE repo = ?", ('["Marvis-AI/marvis-tts-250m-v0.2"]', user))
    world.conn.commit()
    _queued_for_screen(world.conn, "Marvis-AI/marvis-tts-250m-v0.2-MLX-8bit", lane="tts")
    i = inv(world)
    by = {e.path: e for e in i.entries}
    assert by[str(base)].group == disk.REJECTED and "needed by OmniSVG/OmniSVG1.1_4B" in by[str(base)].why
    assert by[str(tok)].group == disk.QUEUED and "needed by Marvis-AI/marvis-tts-250m-v0.2-MLX-8bit" in by[str(tok)].why
    got = disk.clean(i, NOW, world.conn)
    assert "Qwen/Qwen2.5-VL-3B-Instruct" in [r["repo"] for r in got["rejected"]] and not base.exists()
    assert tok.exists()


def test_weights_with_no_owner_go_past_the_deadline_stamped_and_young_ones_stay(world):
    old = make_repo(world.hub, "org/by-hand-old")
    young = make_repo(world.hub, "org/by-hand-young")
    _aged(world.conn, "org/by-hand-old", disk.QUEUED_DEADLINE_S / DAY + 1)
    _aged(world.conn, "org/by-hand-young", 1)
    i = inv(world)
    assert {e.group for e in i.entries} == {disk.UNKNOWN}
    got = disk.clean(i, NOW, world.conn)
    assert [r["repo"] for r in got["evicted"]] == ["org/by-hand-old"]
    assert not old.exists() and young.exists()
    row = world.conn.execute("SELECT state, removed_by FROM downloads WHERE repo = 'org/by-hand-old'").fetchone()
    assert (row["state"], row["removed_by"]) == ("removed", disk.UNOWNED)
    assert world.conn.execute("SELECT count(*) AS n FROM proposals WHERE name = 'org/by-hand-old'").fetchone()["n"] == 0


# ---- 5. a refused deploy poll pages once per cause --------------------------------------------------

def _environ(tmp_path, min_gb):
    root = tmp_path / "hf"
    root.mkdir(exist_ok=True)
    return {"HF_HOME": str(root), "HF_MIN_FREE_GB": str(min_gb)}


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/deploy.py:refused")
def test_a_deploy_poll_refused_by_env_problem_alerts_once_while_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_queue", lambda *a, **k: pytest.fail("a refused poll queued a deploy"))
    monkeypatch.setattr(deploy, "confirm", lambda *a, **k: "")
    alerts, said = [], []
    low = _environ(tmp_path, 10 ** 9)
    for _ in range(3):
        got = deploy.poll(environ=low, alert=alerts.append)
        assert got["queued"] is None and got["refused"]["kind"] == env.LOW_SPACE
    assert len(alerts) == 1 and "deploys refused" in alerts[0]
    gone = {"HF_HOME": str(tmp_path / "Volumes" / "Gone" / "hf"), "HF_MIN_FREE_GB": "0"}
    deploy.refused(gone, alerts.append, said.append)
    deploy.refused(gone, alerts.append, said.append)
    assert len(alerts) == 2 and env.NOT_MOUNTED in alerts[1]
    assert deploy.refused(_environ(tmp_path, 0), alerts.append, said.append) is None
    assert len(alerts) == 2 and not deploy._refused_mark().exists()
    assert len(said) == 2 and "no longer refused" in said[1]


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:HF_MIN_FREE_GB")
def test_env_sh_and_the_deploy_poll_read_the_same_hf_min_free_gb(tmp_path):
    root = tmp_path / "hf"
    root.mkdir()
    for min_gb, refused in ((10 ** 9, True), (0, False)):
        rc, _home, _err = run_env(hf_root=str(root), min_free_gb=str(min_gb))
        kind, _why = env.refusal(str(root), env.min_free_gb({"HF_MIN_FREE_GB": str(min_gb)}), record=False)
        assert (rc != 0, bool(kind)) == (refused, refused)
