"""Each watchdog wake asks every resident text lane a known-answer completion; outages are runs of lane_probes rows (#924)."""
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time

import pytest

from harness import availability, cli, delegate, exclusive, loopback, morning, serving
from harness import lane_probe as lp
from harness import memory_store as ms
from harness import watchdog as wd
from harness.commands import morning as morning_cmd

MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"
T0 = time.mktime((2026, 10, 17, 0, 50, 0, 0, 0, -1))
WAKE = 300.0
OK = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
      "usage": {"prompt_tokens": 14, "completion_tokens": 2}}


class Lane(http.server.BaseHTTPRequestHandler):
    """Answers as the extract lane's mlx_lm.server did on 2026-10-17, healthy and after its generation thread died."""
    state: dict = {}

    def _send(self, code, body):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        s = self.state
        if self.path == "/sohot/loaded":
            self._send(200, {"model": MODEL if s["loaded"] else None})
        elif self.path == "/health":
            self._send(503, {"status": "unavailable"}) if s["mode"] == "dead" else self._send(200, {"status": "ok"})
        else:
            self._send(404, {})

    def do_POST(self):
        s = self.state
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        s["posts"].append({"headers": dict(self.headers), "body": body})
        mode = s["mode"]
        if mode == "hang":
            s["release"].wait(60)
            mode = "ok"
        if s.get("delay"):
            time.sleep(s["delay"])
        if mode == "dead":
            self._send(404, {"error": "generation thread died"})
        elif mode == "empty":
            self._send(200, b"")
        elif mode == "blank":
            self._send(200, {"choices": [{"message": {"content": ""}}]})
        else:
            self._send(200, OK)

    def log_message(self, *a):
        pass


class Fake:
    def __init__(self, base, state, sender):
        self.base, self.state, self.sender = base, state, sender

    def resolve(self, lane):
        return MODEL, serving.Route(self.base, MODEL, {})

    def wake(self, conn, k, mode=None, **kw):
        if mode is not None:
            self.state["mode"] = mode
        return lp.wake(conn, T0 + k * WAKE, lanes=("extract",), sender=self.sender, resolve=self.resolve, **kw)[0]


@pytest.fixture
def lane(tmp_path, monkeypatch):
    servers, fakes, senders = [], set(), []
    real = serving.engine_at
    monkeypatch.setattr(serving, "engine_at", lambda b, *a, **kw: serving.DEFAULT if serving.bare(b) in fakes
                        else real(b, *a, **kw))

    def start(mode="ok", loaded=True):
        state = {"mode": mode, "loaded": loaded, "posts": [], "release": threading.Event()}
        srv = loopback.ThreadingHTTPServer(("127.0.0.1", 0), type("L", (Lane,), {"state": state}))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append((srv, state))
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        fakes.add(base)
        sender = lp.Sender(tmp_path / f"wd{len(servers)}")
        senders.append(sender)
        return Fake(base, state, sender)
    start.fakes = fakes
    yield start
    for srv, state in servers:
        state["release"].set()
    for sender in senders:
        for proc in sender.left:
            try:
                proc.wait(timeout=20)
            except Exception:  # noqa: BLE001
                proc.kill()
    for srv, _ in servers:
        srv.shutdown()
        srv.server_close()


def _store(tmp_path):
    return ms.connect(tmp_path / "s.db")


def _rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM lane_probes ORDER BY at, id")]


def test_a_replay_of_the_10_17_death_is_one_incident_bounded_by_the_wakes_around_it(tmp_path, lane):
    conn, f = _store(tmp_path), lane()
    modes = ["ok", "ok", "dead", "dead", "dead", "ok", "ok"]
    got = [f.wake(conn, k, m) for k, m in enumerate(modes)]
    assert [r["outcome"] for r in got] == ["up", "up", "down", "down", "down", "up", "up"]
    assert got[2]["http_status"] == 404 and "generation thread died" in got[2]["error"]
    assert got[0]["engine"] == serving.DEFAULT and got[0]["base"] == f.base and got[0]["model"] == MODEL
    assert got[0]["completion_tokens"] == 2 and got[0]["prompt_tokens"] == 14
    r = availability.report(conn, T0 - 1, T0 + 10 * WAKE)
    [i] = r["incidents"]
    assert (i["after"], i["first_down"], i["last_down"], i["up_at"]) == (T0 + WAKE, T0 + 2 * WAKE, T0 + 4 * WAKE,
                                                                          T0 + 5 * WAKE)
    assert not i["open"] and i["at_least_s"] == 2 * WAKE and i["at_most_s"] == 4 * WAKE
    assert "generation thread died" in i["error"]
    u = r["lanes"]["extract"]
    assert (u["up"], u["down"], u["slow"], u["judged"], u["rate"]) == (4, 3, 0, 7, 4 / 7)


def test_an_incident_still_open_has_no_end_and_is_reported_from_before_the_window(tmp_path, lane):
    conn, f = _store(tmp_path), lane()
    for k, m in enumerate(["ok", "dead", "dead", "dead"]):
        f.wake(conn, k, m)
    r = availability.report(conn, T0 + 2.5 * WAKE, T0 + 4 * WAKE)
    [i] = r["incidents"]
    assert i["open"] and i["after"] == T0 and i["first_down"] == T0 + WAKE and i["up_at"] is None
    assert r["lanes"]["extract"]["open"]
    assert "still down" in availability.incident_line(i)


def test_slow_and_skipped_rows_neither_open_nor_close_an_incident():
    rows = [{"lane": "x", "at": float(t), "outcome": o, "error": ""} for t, o in
            enumerate(["up", "skipped", "down", "slow", "skipped", "down", "up", "slow", "skipped"])]
    [i] = availability.incidents(rows)
    assert (i["after"], i["first_down"], i["last_down"], i["up_at"], i["downs"]) == (0.0, 2.0, 5.0, 6.0, 2)


@pytest.mark.parametrize("mode", ["empty", "blank"])
def test_a_200_without_the_known_answer_is_down(tmp_path, lane, mode):
    conn, f = _store(tmp_path), lane()
    row = f.wake(conn, 0, mode)
    assert row["outcome"] == "down" and row["http_status"] == 200 and row["error"]


def test_each_lane_is_judged_by_its_own_known_answer():
    def sent(content):
        return {"status": 200, "body": json.dumps({"choices": [{"message": {"content": content}}]})}
    assert lp.judge("code", sent("OK"))["outcome"] == "up"
    assert lp.judge("code", sent("Sure, here is some code"))["outcome"] == "down"
    assert lp.judge("decide", sent('{"answer": "A"}'))["outcome"] == "up"
    assert lp.judge("decide", sent('{"answer": "B"}'))["outcome"] == "down"
    assert lp.judge("claims", sent('{"c": []}'))["outcome"] == "up"
    assert lp.judge("claims", sent("not json"))["outcome"] == "down"
    assert lp.judge("extract", {"status": 200, "body": ""})["outcome"] == "down"
    assert lp.judge("extract", {"status": None, "timed_out": True, "error": "x"})["outcome"] == "slow"
    assert lp.judge("extract", {"status": None, "error": "ConnectionRefusedError"})["outcome"] == "down"


def test_the_schema_lanes_send_their_schema_and_every_probe_turns_thinking_off():
    assert lp.request("decide", "m")["response_format"]["json_schema"]["name"] == "decide"
    assert lp.request("claims", "m")["response_format"]["json_schema"]["name"] == "claims"
    body = lp.request("extract", "m")
    assert "response_format" not in body and body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["temperature"] == 0 and body["max_tokens"] == lp.max_tokens("extract")


def test_a_cold_model_gets_no_completion(tmp_path, lane):
    conn, f = _store(tmp_path), lane(loaded=False)
    row = f.wake(conn, 0)
    assert row["outcome"] == "skipped" and "not resident" in row["reason"]
    assert f.state["posts"] == []


def test_a_held_machine_gets_no_completion(tmp_path, lane):
    conn, f = _store(tmp_path), lane()
    fd = os.open(exclusive.lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        assert exclusive._take(fd)
        row = f.wake(conn, 0)
    finally:
        exclusive._release(fd)
        os.close(fd)
    assert row["outcome"] == "skipped" and "held" in row["reason"]
    assert f.state["posts"] == []


def test_a_lane_served_by_another_host_is_probed_while_this_machine_is_held(tmp_path, lane, monkeypatch):
    conn, f = _store(tmp_path), lane()
    monkeypatch.setattr(serving, "loopback", lambda base: False)
    row = f.wake(conn, 0, busy=lambda: "evals.run pid 1")
    assert row["outcome"] == "up" and len(f.state["posts"]) == 1


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/lane_probe.py:TIMEOUT_S")
def test_every_text_lane_has_a_timeout_and_a_budget_and_a_lane_outside_the_tables_gets_the_default():
    from harness import gateway
    for name in gateway.TEXT_LANES:
        assert lp.timeout(name) > 0 and lp.max_tokens(name) > 0
    assert lp.timeout("a-new-lane") == lp.TIMEOUT_DEFAULT_S and lp.max_tokens("a-new-lane") == lp.MAX_TOKENS_DEFAULT
    assert lp.timeout("code") > lp.timeout("extract")


class Crashing(lp.Sender):
    def start(self, lane, url, headers, body, hold):
        _, result = self._paths(lane)
        return subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"]), result


@pytest.mark.gauntlet("a-fact-about-the-harness-recorded-as-a-verdict-on-the-subject",
                      site="harness/lane_probe.py:Sender.collect")
def test_a_probe_whose_own_sender_dies_is_skipped_never_down(tmp_path, lane):
    conn, f = _store(tmp_path), lane()
    [row] = lp.wake(conn, T0, lanes=("extract",), sender=Crashing(tmp_path / "wdc"), resolve=f.resolve)
    assert row["outcome"] == "skipped" and "exited 7" in row["reason"]


def _until(pred, limit=20.0):
    end = time.monotonic() + limit
    while not pred():
        assert time.monotonic() < end, "timed out waiting"
        time.sleep(0.05)


def test_a_server_that_never_answers_is_slow_and_is_not_asked_again_while_the_first_is_out(tmp_path, lane,
                                                                                         monkeypatch):
    monkeypatch.setattr(lp, "TIMEOUT_DEFAULT_S", 0.5)
    conn, f = _store(tmp_path), lane()
    first = f.wake(conn, 0, "hang")
    assert first["outcome"] == "slow" and "left to finish" in first["reason"]
    _until(lambda: len(f.state["posts"]) == 1)
    second = f.wake(conn, 1)
    assert second["outcome"] == "skipped" and "has not returned" in second["reason"]
    assert len(f.state["posts"]) == 1
    f.state["mode"] = "ok"
    f.state["delay"] = 0.6
    f.state["release"].set()
    _until(lambda: not f.sender.in_flight("extract"))
    monkeypatch.setattr(lp, "TIMEOUT_DEFAULT_S", 30.0)
    assert f.wake(conn, 2)["outcome"] == "up" and len(f.state["posts"]) == 2


def test_a_server_that_refuses_connections_is_down_without_a_completion(tmp_path, lane, monkeypatch):
    # Windows retries a refused loopback SYN for about 2 s, as long as the residency budget itself.
    monkeypatch.setattr(delegate, "RESIDENCY_TIMEOUT_S", 10.0)
    lane()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{s.getsockname()[1]}"
    s.close()
    lane.fakes.add(base)
    conn = _store(tmp_path)
    [row] = lp.wake(conn, T0, lanes=("extract",), sender=lp.Sender(tmp_path / "wdx"),
                    resolve=lambda lane: (MODEL, serving.Route(base, MODEL, {})))
    assert row["outcome"] == "down" and "refused" in row["reason"]


def test_a_direct_probe_is_logged_as_the_gateway_would_with_purpose_watchdog(tmp_path, lane):
    conn, f = _store(tmp_path), lane()
    f.wake(conn, 0, "ok")
    f.wake(conn, 1, "dead")
    got = [dict(r) for r in conn.execute("SELECT * FROM gateway_requests ORDER BY at")]
    assert [g["purpose"] for g in got] == ["watchdog", "watchdog"]
    assert [g["error_code"] for g in got] == ["", "404"] and {g["lane"] for g in got} == {"extract"}
    assert got[0]["client"] == "soh-delegate" and got[0]["completion_tokens"] == 2


def test_a_probe_through_the_gateway_is_tagged_watchdog_and_left_for_the_gateway_to_log(tmp_path, lane, monkeypatch):
    conn, f = _store(tmp_path), lane()
    monkeypatch.setenv("SOHOT_GATEWAY_URL", f.base)
    monkeypatch.setattr(delegate, "upstream", lambda where, config=None: (f.base, MODEL))
    monkeypatch.delenv("SOHOT_PURPOSE", raising=False)
    row = f.wake(conn, 0, "ok")
    assert row["outcome"] == "up"
    [post] = f.state["posts"]
    assert {k.lower(): v for k, v in post["headers"].items()}["x-litellm-tags"] == "purpose:watchdog"
    assert conn.execute("SELECT COUNT(*) FROM gateway_requests").fetchone()[0] == 0


class Quiet(wd.Probes):
    """Real lane probes; nothing else on the machine to see."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path

    def processes(self):
        return []

    def launchd_loaded(self, service):
        return None

    def launchd_pid(self, service):
        return None

    def heartbeat(self):
        return None

    def job_pids(self):
        return {}

    def progress(self, evals):
        return []

    def lock(self):
        return {}

    def resident(self):
        return []

    def pressure(self):
        return None

    def gateway_up(self):
        return None

    def fallbacks(self, conn):
        return []

    def state(self):
        d = self.tmp / "wd"
        d.mkdir(exist_ok=True)
        return d


def test_the_watchdog_wake_probes_every_text_lane_and_a_down_lane_is_not_all_clear(tmp_path, lane, monkeypatch):
    f = lane()
    monkeypatch.setattr(wd.Probes, "lanes", wd.Probes.lanes.real)

    def resolve(name):
        if name != "extract":
            raise delegate.Refused(f"no {name} model here")
        return f.resolve(name)
    monkeypatch.setattr(lp, "_resolve", resolve)
    conn = _store(tmp_path)
    said = []
    for k, mode in enumerate(["ok", "dead"]):
        f.state["mode"] = mode
        out = wd.wake(conn, probes=Quiet(tmp_path), now=T0 + k * WAKE, say=said.append)
    assert out["down"] == ["extract"]
    rows = _rows(conn)
    from harness import gateway
    assert sorted({r["lane"] for r in rows}) == sorted(gateway.TEXT_LANES) and len(rows) == 2 * len(gateway.TEXT_LANES)
    ex = [r for r in rows if r["lane"] == "extract"]
    assert [r["outcome"] for r in ex] == ["up", "down"]
    assert all(r["machine_id"] == wd._machine(conn) for r in rows)
    assert {r["outcome"] for r in rows if r["lane"] != "extract"} == {"skipped"}
    assert sum("all clear" in s for s in said) == 1
    assert any(s.startswith("lane extract: down") for s in said)


def test_soh_availability_prints_each_lane_and_each_incident(tmp_path, lane, capsys):
    conn, f = ms.connect(), lane()
    now = time.time()
    here = availability.here(conn)
    for k, mode in enumerate(["ok", "dead", "dead", "ok"]):
        f.state["mode"] = mode
        lp.wake(conn, now - (4 - k) * WAKE, lanes=("extract",), sender=f.sender, resolve=f.resolve, machine_id=here)
    conn.close()
    assert cli.main(["availability", "--days", "1", "--json"]) == 0
    out = capsys.readouterr()
    got = json.loads(out.out)
    assert got["lanes"]["extract"]["down"] == 2 and got["lanes"]["extract"]["up"] == 2
    [i] = got["incidents"]
    assert i["first_down"] == now - 3 * WAKE and i["up_at"] == now - WAKE and not i["open"]
    assert "incident extract: down after" in out.err and "BELOW TARGET" in out.err


def _gather(conn, now, health=None):
    return morning.gather(conn, now, now - 12 * 3600, beat={}, gh=lambda argv: "[]", git=lambda argv: "",
                          where=None, lanes=lambda c: [], health=health)


def test_morning_names_an_open_incident_once_in_place_of_the_point_in_time_line(tmp_path, lane):
    conn, f = ms.connect(), lane()
    for k, mode in enumerate(["ok", "dead", "dead"]):
        f.wake(conn, k, mode, machine_id=availability.here(conn))
    dead = {"lane": "extract", "spec": MODEL, "base": f.base, "generating": False, "why": ""}
    r = _gather(conn, T0 + 3 * WAKE, health=lambda lane: dead)
    lines = [n for n in r["needs"] if "extract" in n]
    assert len(lines) == 1 and lines[0].startswith("lane extract: down after") and "still down" in lines[0]
    assert morning.lane_dead(r)
    head = morning.headline(r, "facts", ask=lambda p: pytest.fail("a dead lane must not be asked"))
    assert head["by"] == "deterministic"
    shown = morning_cmd.render(r)
    assert "incidents 1" in shown and not any("CANNOT GENERATE" in s for s in shown)


def test_morning_lists_a_closed_incident_without_calling_a_person(tmp_path, lane):
    conn, f = ms.connect(), lane()
    for k, mode in enumerate(["ok", "dead", "ok"]):
        f.wake(conn, k, mode, machine_id=availability.here(conn))
    r = _gather(conn, T0 + 3 * WAKE)
    assert len(r["incidents"]) == 1 and not r["incidents"][0]["open"]
    assert not any("extract" in n for n in r["needs"])
    assert any("up again" in s for s in morning_cmd.render(r))
