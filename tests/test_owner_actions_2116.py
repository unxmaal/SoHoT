"""Owner actions on the status page: only an allowed device's own connection may press one. #2116."""
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
DEVICE = {"id": "nPHONEstable", "name": "phone.example.ts.net", "user": "owner@example.com"}
STRANGER = {"id": "nOTHERstable", "name": "laptop.example.ts.net", "user": "owner@example.com"}
MAIN = "a" * 40
R = {"generated": NOW, "deploy": {"head": "b" * 40, "main": MAIN, "wait": None},
     "discovery": {"queued": {"jobs": [{"id": "0042", "step": "sweep"}]}}}


def _who(ip):
    return {PHONE: DEVICE, OTHER: STRANGER}[ip]


class Home:
    """A scratch home with one allowed device, a fake lookup, a fake verb runner and the audit log."""

    def __init__(self, tmp_path, devices=DEVICE["id"]):
        self.home = tmp_path
        if devices is not None:
            (tmp_path / oa.DEVICES).write_text(devices + "\n", encoding="utf-8")
        self.ran, self.looked = [], []

    def lookup(self, ip):
        self.looked.append(ip)
        return _who(ip)

    def run(self, cmd, **kw):
        self.ran.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="held\n", stderr="")

    def press(self, form, peer=PHONE, headers=(), now=NOW, lookup=None, r=R):
        return oa.press(peer, dict.fromkeys(headers, "x"), form, r, now=now, home=self.home,
                        lookup=lookup or self.lookup, local=lambda ip: ip.startswith("127.") or ip == "::1", run=self.run)

    def token(self, peer=PHONE, who=DEVICE, now=NOW):
        return oa.token(peer, who, now)

    def log(self):
        p = self.home / oa.AUDIT
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def confirm(self, form, **kw):
        code, page = self.press(form, **kw)
        assert code == 200, page
        return page.split("name='confirm' value='")[1].split("'")[0]


def test_an_allowed_device_confirms_and_the_verb_runs_once_with_fixed_arguments(tmp_path):
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
    assert second["device"] == DEVICE["name"] and second["peer"] == PHONE and second["action"] == "benchmarks_hold"
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
def test_loopback_is_refused_and_logged_without_a_lookup(tmp_path, peer):
    h = Home(tmp_path)
    code, _ = h.press({"token": h.token(peer), "action": "queue_resume"}, peer=peer)
    assert code == 403 and h.ran == [] and h.looked == []
    assert h.log()[-1]["outcome"] == "refused: a request from this machine" and h.log()[-1]["peer"] == peer


@pytest.mark.parametrize("ip", ["127.0.0.1", "127.9.9.9", "::1", "::ffff:127.0.0.1", "0.0.0.0", "not-an-address", ""])
def test_loopback_in_every_spelling_is_this_machine(ip):
    assert oa.is_local(ip, binds=lambda a: False)


def test_an_address_this_machine_holds_is_this_machine_and_a_far_one_is_not():
    assert oa.is_local(PHONE, binds=lambda a: True)
    assert not oa.is_local(PHONE, binds=lambda a: False)
    assert oa.is_local(f"::ffff:{PHONE}", binds=lambda a: a == PHONE)
    assert oa._binds("127.0.0.1") and not oa._binds(PHONE)


def test_another_device_is_refused_and_logged(tmp_path):
    h = Home(tmp_path)
    code, _ = h.press({"token": h.token(OTHER, STRANGER), "action": "queue_resume"}, peer=OTHER)
    assert code == 403 and h.ran == [] and h.looked == [OTHER]
    assert h.log()[-1]["outcome"] == "refused: not an allowed device"


def test_a_failed_lookup_is_refused_and_logged(tmp_path):
    h = Home(tmp_path)

    def down(ip):
        raise LookupError("whois exited 1")
    code, _ = h.press({"token": h.token(), "action": "queue_resume"}, lookup=down)
    assert code == 403 and h.ran == []
    assert h.log()[-1]["outcome"] == "refused: identity lookup unavailable: whois exited 1"


def test_a_lookup_that_answers_nonsense_is_a_refusal(tmp_path):
    h = Home(tmp_path)
    for bad in (lambda ip: None, lambda ip: {}, lambda ip: {"id": "", "name": ""}):
        assert h.press({"token": h.token(), "action": "queue_resume"}, lookup=bad)[0] == 403
    assert h.ran == []


def test_a_missing_stale_or_borrowed_token_is_refused_and_logged(tmp_path):
    h = Home(tmp_path)
    for tok in ("", "123.abc", h.token(OTHER), h.token(who=STRANGER), h.token(now=NOW - oa.TOKEN_TTL_S - 1)):
        code, _ = h.press({"token": tok, "action": "queue_resume"})
        assert code == 403 and h.log()[-1]["outcome"].startswith("refused: the page token is missing or stale")
    assert h.press({"action": "queue_resume"})[0] == 403
    assert h.ran == [] and len(h.log()) == 6


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
    assert code == 403 and h.looked == [] and h.ran == []
    assert h.log()[-1]["outcome"].startswith("refused: a forwarded request")


@pytest.mark.parametrize("devices", [None, "", "# nobody yet\n\n"])
def test_with_no_allowed_device_the_page_is_read_only_and_nothing_is_looked_up(tmp_path, devices):
    h = Home(tmp_path, devices=devices)
    assert oa.panel_for(PHONE, {}, R, home=tmp_path, lookup=h.lookup, local=lambda ip: False) == ""
    code, _ = h.press({"token": h.token(), "action": "queue_resume"})
    assert code == 403 and h.looked == [] and h.ran == []
    assert h.log()[-1]["outcome"].startswith("refused: no allowed device is configured")


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/owner_actions.py:allowed:except")
def test_a_device_list_that_cannot_be_read_is_refused_as_that_not_as_an_empty_one(tmp_path):
    h = Home(tmp_path, devices=None)
    assert oa.allowed(tmp_path) == set()
    (tmp_path / oa.DEVICES).mkdir()
    with pytest.raises(OSError):
        oa.allowed(tmp_path)
    code, _ = h.press({"token": h.token(), "action": "queue_resume"})
    assert code == 403 and h.looked == [] and h.ran == []
    assert h.log()[-1]["outcome"].startswith("refused: the allowed-device list cannot be read")
    assert oa.panel_for(PHONE, {}, R, home=tmp_path, lookup=h.lookup, local=lambda ip: False) == ""
    (tmp_path / oa.DEVICES).rmdir()
    (tmp_path / oa.DEVICES).write_bytes(b"\xff\xfe\x00bad")
    assert oa.caller(PHONE, {}, home=tmp_path, lookup=h.lookup, local=lambda ip: False)[1].startswith("the allowed-device list cannot")


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/owner_actions.py:caller:none-message")
def test_each_refusal_says_its_own_cause(tmp_path):
    h = Home(tmp_path)
    kw = {"home": tmp_path, "local": lambda ip: ip == "127.0.0.1"}

    def down(ip):
        raise LookupError("whois exited 1")
    why = [oa.caller(OTHER, {}, lookup=h.lookup, **kw)[1], oa.caller(PHONE, {}, lookup=down, **kw)[1],
           oa.caller(PHONE, {}, lookup=lambda ip: None, **kw)[1], oa.caller("127.0.0.1", {}, lookup=h.lookup, **kw)[1],
           oa.caller(None, {}, lookup=h.lookup, **kw)[1], oa.caller(PHONE, {"Via": "1.1 p"}, lookup=h.lookup, **kw)[1],
           oa.caller(PHONE, {}, home=tmp_path / "none", lookup=h.lookup, local=kw["local"])[1]]
    assert all(why) and len(set(why)) == len(why)
    assert oa.caller(PHONE, {}, lookup=h.lookup, **kw) == (DEVICE, "")


def test_a_device_is_allowed_by_stable_id_or_by_its_full_name(tmp_path):
    h = Home(tmp_path, devices="# the phone\nPhone.Example.ts.net.  # trailing dot and case ignored")
    assert oa.caller(PHONE, {}, home=tmp_path, lookup=h.lookup, local=lambda ip: False) == (DEVICE, "")
    assert oa.caller(OTHER, {}, home=tmp_path, lookup=h.lookup, local=lambda ip: False)[0] is None


def test_the_panel_is_shown_only_to_the_allowed_device(tmp_path):
    h = Home(tmp_path)
    kw = {"home": tmp_path, "lookup": h.lookup, "local": lambda ip: ip.startswith("127."), "now": NOW}
    got = oa.panel_for(PHONE, {}, R, **kw)
    assert "Owner actions" in got and f"value='{h.token()}'" in got and f"value='{MAIN}'" in got
    assert got.count("<form") == len(oa.ACTIONS) and "method='post'" in got
    assert all(f"value='{a.name}'" in got for a in oa.ACTIONS)
    for peer in (OTHER, "127.0.0.1", None):
        assert oa.panel_for(peer, {}, R, **kw) == ""
    assert oa.panel_for(PHONE, {"x-forwarded-for": PHONE}, R, **kw) == ""


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
                                            "discovery_off"]
    for a in oa.ACTIONS:
        assert (a.offers is not None) == ("{}" in a.argv) and a.argv.count("{}") <= 1
        got = parser.parse_args(a.verb(a.offers(R)[0][0]) if a.offers else list(a.argv))
        assert callable(got.func)


def _proc(rc=0, out=""):
    return lambda cmd, **kw: types.SimpleNamespace(returncode=rc, stdout=out, stderr="")


def test_whois_asks_the_network_about_the_peer_and_reads_its_node():
    seen = []

    def run(cmd, **kw):
        seen.append((cmd, kw.get("timeout")))
        return types.SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
            {"Node": {"StableID": DEVICE["id"], "Name": "Phone.Example.ts.net."}, "UserProfile": {"LoginName": DEVICE["user"]}}))
    assert oa.whois(PHONE, run=run, binary="/bin/ts") == DEVICE
    assert seen == [(["/bin/ts", "whois", "--json", PHONE], oa.WHOIS_TIMEOUT_S)]


def _raises(exc):
    def run(cmd, **kw):
        raise exc
    return run


GOOD = json.dumps({"Node": {"StableID": DEVICE["id"], "Name": DEVICE["name"]}})


@pytest.mark.parametrize("run", [_proc(rc=1, out=GOOD), _proc(out="not json"), _proc(out="{}"), _proc(out="[]"), _proc(out='{"Node": null}'),
                                 _raises(subprocess.TimeoutExpired("ts", 5)), _raises(FileNotFoundError("ts"))])
def test_whois_that_cannot_answer_raises_so_the_caller_is_refused(tmp_path, run):
    with pytest.raises(LookupError):
        oa.whois(PHONE, run=run, binary="/bin/ts")
    h = Home(tmp_path)
    code, _ = h.press({"token": h.token(), "action": "queue_resume"}, lookup=lambda ip: oa.whois(ip, run=run, binary="/bin/ts"))
    assert code == 403 and h.log()[-1]["outcome"].startswith("refused: identity lookup unavailable")


def test_without_a_tailscale_binary_the_lookup_fails_closed(monkeypatch):
    assert oa.tailscale_bin(which=lambda n: "/opt/bin/tailscale", exists=lambda p: True) == "/opt/bin/tailscale"
    assert oa.tailscale_bin(which=lambda n: None, exists=lambda p: p == oa.APP_BIN) == oa.APP_BIN
    assert oa.tailscale_bin(which=lambda n: None, exists=lambda p: False) is None
    monkeypatch.setattr(oa, "tailscale_bin", lambda: None)
    with pytest.raises(LookupError):
        oa.whois(PHONE, run=_proc())


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
    monkeypatch.setattr(sp, "page", lambda r, now=None, extra="": f"<html>{extra}</html>")
    guard = srv.transport_security("0.0.0.0", 8899)
    monkeypatch.setattr(srv, "STATUS_HOSTS", {h.lower() for h in guard.allowed_hosts})
    monkeypatch.setattr(oa, "whois", _who)
    monkeypatch.setattr(oa, "_binds", lambda ip: False)
    ran = []
    monkeypatch.setattr(oa, "run_verb", lambda argv, run=None: ran.append(argv) or {"rc": 0, "out": "ok"})
    (paths.home() / oa.DEVICES).write_text(DEVICE["id"] + "\n", encoding="utf-8")
    app = srv.SERVER.streamable_http_app(transport_security=guard, host="0.0.0.0")
    return TestClient(app, client=(peer, 50000), headers={"host": "localhost:8899"}), ran


def test_the_route_takes_a_post_from_the_allowed_device_and_nothing_else(monkeypatch):
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
    assert client.post("/status/action", data=form, headers={"host": "rebound.example.com"}).status_code == 421
    assert client.post("/status/action", data={**form, "pad": "x" * oa.BODY_MAX}).status_code == 403
    spoofed = client.post("/status/action", data={"token": tok, "action": "queue_resume"}, headers={"x-forwarded-for": PHONE})
    assert spoofed.status_code == 403 and len(ran) == 1


@pytest.mark.parametrize("peer", [OTHER, "127.0.0.1"])
def test_the_route_shows_no_panel_and_takes_no_post_from_anyone_else(monkeypatch, peer):
    client, ran = _client(monkeypatch, peer)
    assert client.get("/status").text == "<html></html>"
    got = client.post("/status/action", data={"token": oa.token(peer, DEVICE), "action": "queue_resume"})
    assert got.status_code == 403 and ran == []
    assert json.loads((paths.home() / oa.AUDIT).read_text(encoding="utf-8").splitlines()[-1])["outcome"].startswith("refused")


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
