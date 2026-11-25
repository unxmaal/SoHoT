"""The LAN status page: each owner-needing state is a banner, a down store still renders, no secret is shown. #2075."""
from __future__ import annotations

import json
import time

import pytest

from harness import deploy_state as ds
from harness import memory_store as ms
from harness import monitor, queue_hold, queue_pause, status_page as sp

NOW = time.time()
NO_FEATURES = lambda conn, now, q: {"rows": []}  # noqa: E731
BEAT = {"status": "finished", "started": NOW - 3600, "finished": NOW - 600, "rc": 0,
        "line": "last discovery loop finished 10m ago, rc 0"}


def _mon(rows=("gateway   OK   Process",), running=True):
    return lambda: {"installed": True, "running": running, "current": True, "webhook": True, "problems": [],
                    "summary": ["Service Name   Status   Type", *rows]}


def _gather(tmp_path, **kw):
    args = {"connect": ms.connect, "beat": BEAT, "where": tmp_path, "mon": _mon(), "features": NO_FEATURES,
            "health": lambda lane: {"lane": lane, "spec": "m", "base": "http://127.0.0.1:1", "generating": True, "why": ""},
            "reach": lambda since, now: [], "flow": lambda now: {"available": False, "why": "no transcripts"}}
    args.update(kw)
    return sp.gather(NOW, **args)


def _both(r) -> str:
    return sp.page(r) + sp.as_json(r)


def test_a_healthy_machine_has_no_banner_and_every_section(tmp_path):
    r = _gather(tmp_path)
    assert r["banner"] == []
    text = sp.page(r)
    assert "Nothing needs you" in text and "class='banner'" not in text
    for title in ("Deploy", "Queue", "Discovery", "Monitor", "Services", "Ratio", "Store"):
        assert f"<h2>{title} <span class='asof'>as of" in text
    assert all(r[k]["as_of"] for k in ("store", "queue", "deploy", "discovery", "monitor", "services", "ratio"))
    assert json.loads(sp.as_json(r))["store"]["up"] is True


def test_a_queue_paused_past_the_stale_alert_is_a_banner(tmp_path):
    from harness import queue_stale
    body = queue_hold.text("owner testing a model", None)
    old = time.strftime(queue_hold._STAMP, time.localtime(NOW - queue_stale.QUEUE_STALE_S - 3600))
    queue_pause._pause_flag().parent.mkdir(parents=True, exist_ok=True)
    queue_pause._pause_flag().write_text(old + body[len(old):], encoding="utf-8")
    r = _gather(tmp_path)
    assert any(b.startswith("queue paused") and "owner testing a model" in b for b in r["banner"])
    assert "PAUSED since" in sp.page(r)


def test_a_recent_queue_pause_shows_but_is_not_a_banner(tmp_path):
    queue_pause.pause("a deploy runs")
    r = _gather(tmp_path)
    assert r["queue"]["paused"] and not [b for b in r["banner"] if b.startswith("queue")]


def test_a_failed_deploy_is_a_banner_and_counts_its_run(tmp_path):
    conn = ms.connect()
    try:
        mid = ms.remember_machine(conn)
        for i, outcome in enumerate(("deployed", ds.ROLLED_BACK, ds.ROLLED_BACK)):
            conn.execute("INSERT INTO deploys (sha, machine_id, stage, outcome, started_at, detail) VALUES (?,?,?,?,?,?)",
                         (f"{i}" * 40, mid, outcome, outcome, NOW - 300 + i, "smoke before the switch failed"))
        conn.commit()
    finally:
        conn.close()
    r = _gather(tmp_path)
    assert r["deploy"]["failing"] == 2
    assert any(b.startswith("deploy failing: 2 in a row") and "smoke before the switch" in b for b in r["banner"])


def test_a_crashed_discovery_run_is_a_banner(tmp_path):
    beat = {**BEAT, "rc": 1, "error": "RuntimeError: the sweep died"}
    r = _gather(tmp_path, beat=beat)
    assert "discovery failed: RuntimeError: the sweep died" in r["banner"]
    stalled = _gather(tmp_path, beat={**BEAT, "status": "stalled", "line": "discovery loop stalled"})
    assert any(b.startswith("discovery stalled") for b in stalled["banner"])


def test_a_failing_monit_check_or_stopped_monit_is_a_banner(tmp_path):
    r = _gather(tmp_path, mon=_mon(rows=("gateway   Does not exist   Process", "system_data   OK   Filesystem")))
    assert r["banner"] == ["check gateway is Does not exist"]
    assert any(b.startswith("monit is not running") for b in _gather(tmp_path, mon=_mon(running=False))["banner"])


def test_with_the_store_down_the_page_still_renders_and_says_so(tmp_path):
    def down():
        raise OSError("connection refused")
    r = _gather(tmp_path, connect=down)
    assert r["banner"][0] == "store down: OSError: connection refused"
    text = sp.page(r)
    assert "DOWN" in text and "store down: running and pending jobs not read" in text
    assert r["monitor"]["checks"] and r["discovery"]["status"] == "finished"
    assert json.loads(sp.as_json(r))["store"]["up"] is False


def test_no_secret_or_webhook_url_reaches_the_page(tmp_path, monkeypatch):
    hook = "https://discord.com/api/webhooks/1234567/abcSECRETtoken"
    monitor.env_path().parent.mkdir(parents=True, exist_ok=True)
    monitor.env_path().write_text(f"{monitor.WEBHOOK}={hook}\n", encoding="utf-8")
    monkeypatch.setenv("SOHOT_PG_PASSWORD", "pgsecretvalue42")
    monitor.alerts_path().parent.mkdir(parents=True, exist_ok=True)
    monitor.alerts_path().write_text(json.dumps(
        {"at": NOW - 60, "kind": "alert", "service": "gateway",
         "description": f"posted to {hook.replace('abcSECRETtoken', 'otherTOKENvalue')} token=ghp_abcdef123456"}) + "\n",
        encoding="utf-8")

    def down():
        raise RuntimeError("no store at postgresql://sohot:pgsecretvalue42@db.example.com:5433/sohot")
    r = _gather(tmp_path, connect=down, beat={**BEAT, "rc": 1, "error": f"webhook {hook} refused; auth pgsecretvalue42 rejected"})
    text = _both(r)
    for secret in ("abcSECRETtoken", "otherTOKENvalue", "ghp_abcdef123456", "pgsecretvalue42",
                   "discord.com/api/webhooks", "db.example.com"):
        assert secret not in text, secret
    assert "<redacted>" in text and r["monitor"]["last_alert"]


@pytest.mark.parametrize("text", ["see http://127.0.0.1:8083/v1", "at http://localhost:8899/mcp",
                                  "at http://" + "box" + ".local:8899/status"])
def test_lan_urls_are_kept(text):
    assert sp.scrub(text, []) == text


def test_cached_gathers_at_most_once_per_refresh():
    calls = []

    def gather(now):
        calls.append(now)
        return {"generated": now}
    sp._cache.clear()
    sp.cached(1000.0, gather)
    sp.cached(1000.0 + sp.REFRESH_S - 1, gather)
    assert calls == [1000.0]
    sp.cached(1000.0 + sp.REFRESH_S, gather)
    assert calls == [1000.0, 1000.0 + sp.REFRESH_S]
    sp._cache.clear()


def _app(monkeypatch, tmp_path):
    srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")
    from starlette.testclient import TestClient
    r = _gather(tmp_path)
    monkeypatch.setattr(sp, "cached", lambda: r)
    guard = srv.transport_security("0.0.0.0", 8899)
    return TestClient(srv.SERVER.streamable_http_app(transport_security=guard, host="0.0.0.0"))


def test_the_mcp_server_serves_status_and_status_json(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path)
    page = client.get("/status", headers={"host": "localhost:8899"})
    assert page.status_code == 200 and "SoHoT status" in page.text and "http-equiv='refresh'" in page.text
    got = client.get("/status.json", headers={"host": "localhost:8899"})
    assert got.status_code == 200 and got.json()["banner"] == []

