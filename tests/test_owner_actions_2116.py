"""Owner actions on the status page: any peer that is not this machine may press one. #2116, #2128."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import types

import pytest

from harness import owner_actions as oa
from harness import paths, status_page as sp

NOW = time.time()
PHONE = "203.0.113.7"
OTHER = "203.0.113.8"
MAIN = "a" * 40
R = {"generated": NOW, "deploy": {"head": "b" * 40, "main": MAIN, "wait": None},
     "discovery": {"queued": {"jobs": [{"id": "0042", "step": "sweep"}]}},
     "stops": {"jobs": {"rows": [{"id": "0007", "title": "t", "state": "failed"}, {"id": "0008", "title": "u", "state": "running"}]},
               "gateway": {"mark": {"at": NOW, "reason": "x"}}},
     "queue": {"running": [{"id": "0008", "kind": "command", "title": "u"}],
               "waiting": [{"id": "0009", "title": "a", "priority": 0, "held": True}, {"id": "0010", "title": "b", "priority": 0, "held": False}]},
     "features": {"rows": [{"kind": "node", "name": "styx", "state": "on"}, {"kind": "node", "name": "olm", "state": "parked"},
                           {"kind": "lane", "name": "code", "state": "on demand"}]}}


class Home:
    """A scratch home, a fake verb runner and the audit log."""

    def __init__(self, tmp_path):
        self.home = tmp_path
        self.ran = []

    def run(self, cmd, **kw):
        self.ran.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="held\n", stderr="")

    def press(self, form, peer=PHONE, headers=(), now=NOW, r=R):
        return oa.press(peer, dict.fromkeys(headers, "x"), form, r, now=now, home=self.home,
                        run=self.run)

    def token(self, peer=PHONE, now=NOW):
        return oa.token(peer, {"name": peer, "id": peer}, now)

    def log(self):
        p = self.home / oa.AUDIT
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def confirm(self, form, **kw):
        code, page = self.press(form, **kw)
        assert code == 200, page
        return page.split("name='confirm' value='")[1].split("'")[0]


def test_a_device_confirms_and_the_verb_runs_once_with_fixed_arguments(tmp_path):
    h = Home(tmp_path)
    form = {"token": h.token(), "action": "benchmarks_hold"}
    code, page = h.press(form)
    assert code == 200 and "soh hold benchmarks" in page and h.ran == []
    nonce = page.split("name='confirm' value='")[1].split("'")[0]
    code, page = h.press({**form, "confirm": nonce})
    assert code == 200 and "Done" in page and "held" in page
    assert h.ran == [[sys.executable, "-m", "harness.cli", "hold", "benchmarks", oa.HELD_BY]]
    first, second = h.log()
    assert first["outcome"] == "asked to confirm" and second["outcome"] == "rc 0"
    assert second["device"] == PHONE and second["peer"] == PHONE and second["action"] == "benchmarks_hold"
    assert second["at"]


def test_one_confirmation_runs_the_action_once(tmp_path):
    h = Home(tmp_path)
    form = {"token": h.token(), "action": "queue_resume"}
    form["confirm"] = h.confirm(form)
    assert h.press(form)[0] == 200
    code, page = h.press(form)
    assert code == 409 and "nothing ran" in page and len(h.ran) == 1
    assert h.log()[-1]["outcome"].startswith("refused: that confirmation was already used")


def test_a_confirmation_is_good_only_for_its_own_action_choice_and_time(tmp_path):
    h = Home(tmp_path)
    tok = h.token()
    nonce = h.confirm({"token": tok, "action": "benchmarks_hold"})
    assert h.press({"token": tok, "action": "gate_hold", "confirm": nonce})[0] == 409
    late = h.confirm({"token": tok, "action": "gate_hold"})
    assert h.press({"token": tok, "action": "gate_hold", "confirm": late}, now=NOW + oa.CONFIRM_TTL_S + 1)[0] == 409
    assert h.press({"token": tok, "action": "gate_hold", "confirm": "made-up"})[0] == 409
    assert h.ran == []


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1"])
def test_a_loopback_peer_can_press(tmp_path, peer):
    h = Home(tmp_path)
    form = {"token": h.token(peer), "action": "queue_resume"}
    code, _ = h.press({**form, "confirm": h.confirm(form, peer=peer)}, peer=peer)
    assert code == 200 and len(h.ran) == 1 and h.log()[-1]["peer"] == peer


def test_a_missing_stale_or_borrowed_token_is_refused_and_logged(tmp_path):
    h = Home(tmp_path)
    for tok in ("", "123.abc", h.token(OTHER), h.token(now=NOW - oa.TOKEN_TTL_S - 1)):
        code, _ = h.press({"token": tok, "action": "queue_resume"})
        assert code == 403 and h.log()[-1]["outcome"].startswith("refused: the page token is missing or stale")
    assert h.press({"action": "queue_resume"})[0] == 403
    assert h.ran == [] and len(h.log()) == 5


def test_an_action_outside_the_list_is_refused_and_logged(tmp_path):
    h = Home(tmp_path)
    for name in ("coherence_apply", "jobs", "deploy now", "", "benchmarks_hold; rm"):
        code, _ = h.press({"token": h.token(), "action": name})
        assert code == 400 and h.log()[-1]["outcome"] == "refused: not one of the listed actions"
    assert h.ran == []


@pytest.mark.parametrize("form", [
    {"action": "deploy_now", "arg": "c" * 40}, {"action": "deploy_now", "arg": "b" * 40}, {"action": "deploy_now"},
    {"action": "deploy_now", "arg": MAIN + " --force"}, {"action": "queue_pause", "arg": "my own words"},
    {"action": "queue_pause"}, {"action": "discovery_off", "arg": "0007"}, {"action": "benchmarks_hold", "arg": "x"},
    {"action": "queue_resume", "arg": "--despite-hold"}])
def test_a_choice_the_page_does_not_offer_is_refused_and_logged(tmp_path, form):
    h = Home(tmp_path)
    code, _ = h.press({"token": h.token(), **form})
    assert code == 400 and h.ran == []
    assert h.log()[-1]["outcome"].startswith("refused: the page does not offer that choice")


@pytest.mark.parametrize("form,argv", [
    ({"action": "deploy_now", "arg": MAIN}, ["deploy", "now", MAIN]),
    ({"action": "queue_pause", "arg": oa.PAUSE_REASONS[0]}, ["jobs", "pause", "--reason", oa.PAUSE_REASONS[0]]),
    ({"action": "discovery_off", "arg": "0042"}, ["jobs", "cancel", "0042"]),
    ({"action": "discovery_on"}, ["discover", "--loop", "--run", "--jobs"]),
    ({"action": "gate_release"}, ["hold", "release", "gpu"])])
def test_an_offered_choice_reaches_the_verb_whole(tmp_path, form, argv):
    h = Home(tmp_path)
    form = {"token": h.token(), **form}
    form["confirm"] = h.confirm(form)
    assert h.press(form)[0] == 200 and h.ran == [[sys.executable, "-m", "harness.cli", *argv]]


@pytest.mark.parametrize("header", ["X-Forwarded-For", "forwarded", "X-Real-IP", "Via"])
def test_a_forwarded_request_is_refused_whoever_the_peer_is(tmp_path, header):
    h = Home(tmp_path)
    code, _ = h.press({"token": h.token(), "action": "queue_resume"}, headers=[header])
    assert code == 403 and h.ran == []
    assert h.log()[-1]["outcome"].startswith("refused: a forwarded request")


def test_only_shas_the_page_lists_are_offered():
    assert oa._shas(R) == [(MAIN, f"origin/main {MAIN[:8]}")]
    assert oa._shas({"deploy": {"head": MAIN, "main": MAIN}}) == []
    assert oa._shas({"deploy": {"head": "", "main": "main; rm -rf"}}) == []
    assert oa._shas({"deploy": {"error": "git failed"}}) == []


def test_every_action_is_an_existing_verb_with_no_free_argument():
    cli = pytest.importorskip("harness.cli")
    parser = cli.build_parser()
    assert [a.name for a in oa.ACTIONS] == ["deploy_now", "benchmarks_hold", "benchmarks_release", "gate_hold",
                                            "gate_release", "queue_pause", "queue_resume", "discovery_on",
                                            "discovery_off", "job_retry", "job_cancel", "job_let", "job_first", "gate_again", "unit_restart", "node_park",
                                            "node_unpark", "lane_reverify"]
    for a in oa.ACTIONS:
        assert (a.offers is not None) == ("{}" in a.argv) and a.argv.count("{}") <= 1
        got = parser.parse_args(a.verb(a.offers(R)[0][0]) if a.offers else list(a.argv))
        assert callable(got.func)


def _raises(exc):
    def run(cmd, **kw):
        raise exc
    return run


def test_a_verb_that_fails_or_hangs_is_shown_and_logged(tmp_path):
    h = Home(tmp_path)
    form = {"token": h.token(), "action": "queue_resume"}
    h.run = lambda cmd, **kw: types.SimpleNamespace(returncode=2, stdout="", stderr="error: no such hold\nTOKEN=hunter2secret")
    code, page = h.press({**form, "confirm": h.confirm(form)})
    assert code == 200 and "Failed" in page and "exited 2" in page and "no such hold" in page and "hunter2secret" not in page
    assert h.log()[-1]["outcome"] == "rc 2"
    h.run = _raises(subprocess.TimeoutExpired("soh", oa.ACTION_TIMEOUT_S))
    code, page = h.press({**form, "confirm": h.confirm(form)})
    assert "did not return" in page and h.log()[-1]["outcome"] == "timed out"


def test_a_done_action_drops_the_cached_status(tmp_path):
    sp.cached(NOW, gather_=lambda now: {"generated": now, "n": 1})
    h = Home(tmp_path)
    form = {"token": h.token(), "action": "queue_resume"}
    h.press({**form, "confirm": h.confirm(form)})
    assert sp.cached(NOW, gather_=lambda now: {"generated": now, "n": 2})["n"] == 2
    sp.forget()


def test_the_waiting_sweep_steps_are_what_discovery_off_offers(tmp_path):
    from harness import memory_store as ms
    from harness import workqueue as wq
    from harness.commands import loop_steps
    step = wq.add(["soh", "discover", "--loop", "--run", "--step", "sweep", "--cycle", "1700000000"], title="sweep")
    wq.add(["soh", "measure"], title="not a sweep step")
    conn = ms.connect()
    try:
        assert loop_steps.waiting(conn) == [{"id": wq.label(step["id"]), "step": "sweep"}]
        got = sp.queued_sweep(conn)
    finally:
        conn.close()
    assert oa._sweep_jobs({"discovery": {"queued": got}}) == [(wq.label(step["id"]), f"job {wq.label(step['id'])} (sweep)")]
    assert sp.queued_sweep(None)["jobs"] == [] and oa._sweep_jobs({"discovery": {"queued": {"error": "x"}}}) == []


def _client(monkeypatch, peer):
    srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")
    from starlette.testclient import TestClient
    monkeypatch.setattr(sp, "cached", lambda: R)
    monkeypatch.setattr(sp, "page", lambda r, now=None, extra="", token="": f"<html>{extra}</html>")
    guard = srv.transport_security("0.0.0.0", 8899)
    ran = []
    monkeypatch.setattr(oa, "run_verb", lambda argv, run=None: ran.append(argv) or {"rc": 0, "out": "ok"})
    app = srv.SERVER.streamable_http_app(transport_security=guard, host="0.0.0.0")
    return TestClient(app, client=(peer, 50000), headers={"host": "localhost:8899"}), ran


def test_the_route_takes_a_post_from_another_device_with_its_token(monkeypatch):
    client, ran = _client(monkeypatch, PHONE)
    page = client.get("/status").text
    tok = page.split("name='token' value='")[1].split("'")[0]
    assert client.get("/status/action").status_code == 405
    assert client.get(f"/status/action?token={tok}&action=queue_resume").status_code == 405
    form = {"token": tok, "action": "queue_resume"}
    asked = client.post("/status/action", data=form)
    assert asked.status_code == 200 and ran == []
    form["confirm"] = asked.text.split("name='confirm' value='")[1].split("'")[0]
    assert client.post("/status/action", data=form).status_code == 200 and ran == [["jobs", "resume"]]
    assert client.post("/status/action", data=form).status_code == 409 and len(ran) == 1
    assert client.post("/status/action", data={**form, "pad": "x" * oa.BODY_MAX}).status_code == 403
    spoofed = client.post("/status/action", data={"token": tok, "action": "queue_resume"}, headers={"x-forwarded-for": PHONE})
    assert spoofed.status_code == 403 and len(ran) == 1


def test_the_route_takes_a_post_from_a_loopback_peer(monkeypatch):
    client, ran = _client(monkeypatch, "127.0.0.1")
    tok = client.get("/status").text.split("name='token' value='")[1].split("'")[0]
    form = {"token": tok, "action": "queue_resume"}
    form["confirm"] = client.post("/status/action", data=form).text.split("name='confirm' value='")[1].split("'")[0]
    assert client.post("/status/action", data=form).status_code == 200 and ran == [["jobs", "resume"]]


def test_the_server_never_takes_the_peer_address_from_a_header(monkeypatch):
    srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")
    import uvicorn
    got = {}
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: got.setdefault("config", self.config))
    monkeypatch.setattr(srv, "listen_sockets", lambda host, port: [])
    monkeypatch.setattr(srv, "stale_report", lambda port, pid: [])
    srv.serve("0.0.0.0", 8899)
    assert got["config"].proxy_headers is False


def test_the_status_page_is_unchanged_without_a_panel():
    from harness import status_view
    r = {"generated": NOW, "refresh_s": 60, "ratio": {"error": "x"}, "monitor": {"error": "x"},
         **{k: {"error": "x"} for k in ("store", "queue", "deploy", "discovery", "services")}}
    plain = status_view.page(r, {}, NOW)
    assert "Owner actions" not in plain and "<form" not in plain
    assert status_view.page(r, {}, NOW, "<div>PANEL</div>").replace("<div>PANEL</div>", "") == plain
