"""#2188: Needs-you holds only what the owner can act on, refused refetches sit in the flow panel, and a download cut short by its job is not held for a day."""
from __future__ import annotations

import re
import time

import pytest
from test_needs_you_2134 import NOW, gather, plant_job
from test_refetch_2161 import EDGE, GIB, _downloaded, _queued

from harness import discovery_flow, job_state, monitor, needs_you, owner_actions, reasons, refetch
from harness import memory_store as ms
from harness import status_view as sv


@pytest.fixture(autouse=True)
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(refetch, "path", lambda: tmp_path / refetch.FILE)


def _planted(tmp_path):
    rows = {"rows": [{"kind": "unit", "name": "mlx", "state": "broken", "by": "exit 1", "since": NOW - 3600}]}
    monitor.record({"at": NOW - 7200, "kind": "memory", "service": "memory_pressure", "description": "pressure warn"}, tmp_path)
    refetch.mark("org/a", "the screen", "org/a was downloaded 1.0 h ago", now=NOW - 100)
    return gather(tmp_path, features=lambda c, n, q: rows, reach=lambda s, n: [{"node": "styx", "down_now": True, "down_s": 1800}])


def test_every_needs_you_item_carries_an_owner_button(tmp_path):
    r = _planted(tmp_path)
    assert {"unit-mlx", "node-styx", "monit-memory_pressure"} <= {c["key"] for c in r["needs_you"]}
    mine = needs_you.owner_items(r["needs_you"])
    assert [c["key"] for c in mine] == ["unit-mlx"]
    known = {a.name if hasattr(a, "name") else a[0] for a in owner_actions.ACTIONS}
    assert all(c["fix"] and {f["action"] for f in c["fix"]} <= known for c in mine)
    html = sv._band(r, NOW, "tok")
    needs, folded = html.split("<details", 1)
    assert needs.count("<article") == 1 and needs.count("<form") >= 1
    assert "stopped with nothing for you to press" in folded and "node-styx" in folded


def test_a_refused_refetch_is_not_a_needs_you_item(tmp_path):
    r = _planted(tmp_path)
    assert not [c for c in r["needs_you"] if c["key"].startswith("refetch-")]
    assert "refetch" not in (r.get("stops") or {})
    assert refetch.read(NOW)["org/a"]["via"] == "the screen"


def test_the_flow_panel_sums_the_refused_downloads_in_one_row():
    now = time.time()
    conn = ms.connect()
    try:
        _downloaded(conn, "org/a", gib=48.1, ago_s=3600, now=now)
        _downloaded(conn, "org/b", gib=30.0, ago_s=1800, now=now)
        for repo in ("org/a", "org/b"):
            refetch.mark(repo, "the screen", "no verdict since", now=now - 60)
        fl = discovery_flow.gather(conn, now)
    finally:
        conn.close()
    assert (fl["refused"]["n"], fl["refused"]["gib"]) == (2, 78.1)
    html = sv._flow(fl, now, [])
    assert "2 model(s) refused a second download within 24 h, 78.1 GiB not refetched" in html
    assert len(re.findall(r"data-refused='org/", html)) == 2


def _repo_cut_short(conn, tmp_path, state, *, queued_after=None, job_window=(-1000, 1000)):
    now = time.time()
    _queued(conn, EDGE)
    _downloaded(conn, EDGE, ago_s=3600, now=now)
    at = now - 3600
    plant_job(tmp_path, state, "discover screen", started=at + job_window[0], finished=at + job_window[1], rc=-15 if state == "cancelled" else 1)
    if queued_after:
        ms.decide(conn, EDGE, "queued", tier=ms.SCREEN, detail="no screen window", reason=queued_after)
        conn.commit()
    return now


@pytest.mark.parametrize("state", [job_state.CANCELLED, job_state.FAILED])
def test_a_download_whose_screen_job_was_cancelled_or_crashed_may_be_fetched_again(tmp_path, state):
    conn = ms.connect()
    try:
        now = _repo_cut_short(conn, tmp_path, state)
        assert refetch.refusal(conn, EDGE, "the screen", now=now) == ""
        assert refetch.read(now) == {}
    finally:
        conn.close()


def test_a_screen_that_finished_without_a_verdict_keeps_its_block(tmp_path):
    conn = ms.connect()
    try:
        now = _repo_cut_short(conn, tmp_path, job_state.DONE)
        assert "no verdict was written since" in refetch.refusal(conn, EDGE, "the screen", now=now)
    finally:
        conn.close()


def test_a_cancelled_job_that_had_already_queued_the_candidate_keeps_the_block(tmp_path):
    conn = ms.connect()
    try:
        now = _repo_cut_short(conn, tmp_path, job_state.CANCELLED, queued_after=reasons.MEMORY)
        assert "no verdict was written since" in refetch.refusal(conn, EDGE, "the screen", now=now)
    finally:
        conn.close()


def test_a_job_that_ended_before_the_download_started_does_not_release_it(tmp_path):
    conn = ms.connect()
    try:
        now = _repo_cut_short(conn, tmp_path, job_state.CANCELLED, job_window=(-5000, -4000))
        assert "no verdict was written since" in refetch.refusal(conn, EDGE, "the screen", now=now)
    finally:
        conn.close()


# ---- the cold /status build ---------------------------------------------------------------------------------

def test_the_deploy_path_is_asked_of_launchd_once_in_a_window(monkeypatch):
    import subprocess
    from harness import paths
    asked = []
    monkeypatch.setattr(paths, "_deploy_seen", {})
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: asked.append(argv) or subprocess.CompletedProcess(argv, 0, "/d/releases/1\n", ""))
    got = [paths.deploy_link() for _ in range(5)]
    assert len(asked) == 1 and {str(g) for g in got} == {"/d/releases/1"}
    monkeypatch.setattr(paths, "DEPLOY_LINK_TTL_S", -1.0)
    paths.deploy_link()
    assert len(asked) == 2


def test_the_served_page_reuses_its_slow_sections_but_a_plain_gather_and_an_owner_action_do_not(tmp_path, monkeypatch):
    from harness import lane_gate, status_page
    seen = []
    monkeypatch.setattr(status_page, "_slow_seen", {})
    monkeypatch.setattr(lane_gate, "status", lambda conn, now=None: seen.append(1) or {"closed": [], "opened": [], "down": []})
    gather(tmp_path, memo=True)
    gather(tmp_path, memo=True)
    assert len(seen) == 1
    gather(tmp_path)
    assert len(seen) == 2, "a gather that did not ask for the memo reads fresh"
    status_page.forget()
    gather(tmp_path, memo=True)
    assert len(seen) == 3


def test_the_server_builds_the_page_once_at_start(monkeypatch):
    from harness import status_page
    built = []
    monkeypatch.setattr(status_page, "_cache", {})
    monkeypatch.setattr(status_page, "gather", lambda now=None, **k: built.append(k) or {"generated": time.time()})
    status_page.warm()
    assert built == [{"memo": True}]
    status_page.cached()
    assert len(built) == 1


def test_serve_starts_the_warm_up_before_it_runs(monkeypatch):
    import threading
    srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")
    import uvicorn
    warmed = threading.Event()
    monkeypatch.setattr("harness.status_page.warm", warmed.set)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: None)
    monkeypatch.setattr(srv, "listen_sockets", lambda host, port: [])
    monkeypatch.setattr(srv, "stale_report", lambda port, pid: [])
    srv.serve("0.0.0.0", 8899)
    assert warmed.wait(10)


def test_the_deploy_section_reads_the_last_five_deploy_jobs_not_the_whole_table(tmp_path):
    from harness import deploy
    from harness import workqueue as wq
    ids = [plant_job(tmp_path, "done", title=f"j{i}", started=1.0, finished=2.0, rc=0) for i in range(9)]
    conn = ms.connect()
    try:
        deploy_ids = [ids[i] for i in (0, 1, 3, 4, 5, 7, 8)]
        for i in deploy_ids:
            conn.execute("UPDATE jobs SET kind = ? WHERE id = ?", (deploy.KIND, int(i)))
        conn.commit()
        got = [j["id"] for j in wq.last_of_kind(conn, deploy.KIND, 5)]
        assert got == deploy_ids[-5:]
    finally:
        conn.close()


def test_a_reply_schema_is_checked_once_and_a_bad_one_is_still_refused(monkeypatch):
    import jsonschema

    from harness.checks import claims
    seen = []
    real = jsonschema.Draft202012Validator.check_schema
    monkeypatch.setattr(claims, "_SCHEMAS_OK", set())
    monkeypatch.setattr(jsonschema.Draft202012Validator, "check_schema", staticmethod(lambda s: seen.append(1) or real(s)))
    good = {"type": "object", "properties": {"a": {"type": "string"}}}
    for _ in range(3):
        claims.validate_case("sys", dict(good), [], True)
    assert len(seen) == 1
    for _ in range(2):
        with pytest.raises(ValueError, match="not a JSON schema"):
            claims.validate_case("sys", {"type": 5}, [], True)
    assert len(seen) == 3
