"""`soh audit`: the store's invariants and the serving facts, against the live store, read-only (#492 F)."""
import hashlib
import json
import sqlite3
import time

import pytest
import yaml

from harness import adopt, cli, gateway, live_audit
from harness import memory_store as ms
from harness import runs

SPEC = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
BASE = {"model_list": [{"model_name": "q3-4b", "litellm_params": {
    "model": f"openai/{SPEC}", "api_base": "http://127.0.0.1:8081/v1", "api_key": "not-needed"}}]}


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    monkeypatch.setenv(gateway.ENV_VAR, str(path))
    return path


def _run(conn, tmp_path, passed, spec=SPEC, name="r1"):
    run = tmp_path / f"20261006-000000-{name}"
    run.mkdir(exist_ok=True)
    return runs.record(conn, run, {
        "receipt": {"modality": "code"}, "environment": ms.this_machine(), "specs": {spec: spec},
        "rows": [{"case_id": "c1", "candidate": spec, "passed": passed}]})


def _adopt(conn, run_id, spec=SPEC):
    adopt.record(conn, adopt.Verdict("code", "q3-4b", spec, True, "won", adopt.MEASURED), spec, run_id=run_id)


@pytest.fixture
def live(tmp_path, config):
    conn = ms.connect()
    try:
        _adopt(conn, _run(conn, tmp_path, True))
    finally:
        conn.close()
    gateway.write_served(config)
    from harness import heartbeat
    heartbeat.start()
    heartbeat.finish(0)
    return ms.db_path()


def _checks(got):
    return {c["name"]: c for c in got["checks"]}


def test_a_healthy_store_passes_every_check(live):
    got = live_audit.audit(live)
    assert got["ok"], got
    assert set(_checks(got)) == set(live_audit.CHECKS)


def test_the_audit_never_writes_the_store(live):
    before = hashlib.sha256(live.read_bytes()).hexdigest()
    live_audit.audit(live)
    assert hashlib.sha256(live.read_bytes()).hexdigest() == before
    conn = live_audit.open_readonly(live)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM adoptions")
    finally:
        conn.close()


def test_an_older_store_is_reported_not_migrated(live):
    raw = sqlite3.connect(live)
    raw.execute("UPDATE meta SET value = '40' WHERE key = 'schema'")
    raw.commit()
    raw.close()
    got = live_audit.audit(live)
    assert not _checks(got)["schema"]["ok"]
    raw = sqlite3.connect(live)
    assert raw.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == "40"
    raw.close()


def test_an_adoption_with_no_passing_run_here_fails(tmp_path, config):
    conn = ms.connect()
    try:
        _adopt(conn, _run(conn, tmp_path, False))
    finally:
        conn.close()
    gateway.write_served(config)
    check = _checks(live_audit.audit(ms.db_path()))["adoptions_pass_here"]
    assert not check["ok"] and "code" in check["detail"]


def test_a_reference_model_adopted_for_a_lane_fails(live):
    raw = sqlite3.connect(live)
    raw.execute("INSERT INTO candidates (spec, receipt_key, lane, created_at) VALUES "
                "('claude-code:opus', 'claude-code:opus', 'code', 1)")
    cid = raw.execute("SELECT id FROM candidates WHERE spec = 'claude-code:opus'").fetchone()[0]
    raw.execute("INSERT INTO adoptions (lane, candidate_id, how, adopted_at) VALUES ('code', ?, 'by-hand', ?)",
                (cid, time.time()))
    raw.commit()
    raw.close()
    check = _checks(live_audit.audit(live))["no_reference_served"]
    assert not check["ok"] and "claude-code:opus" in check["detail"]


def test_a_served_alias_that_is_not_the_adoption_fails(live, config):
    gateway.write_served(config, defaults={"code": "q3-4b"})
    path = gateway.served_path(config)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for e in data["model_list"]:
        if e["model_name"] == "sohot-code":
            e["litellm_params"]["model"] = "openai/something-else"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    check = _checks(live_audit.audit(live))["served_matches_adoption"]
    assert not check["ok"] and "sohot-code" in check["detail"]


def test_an_alias_whose_requests_mostly_fail_fails(live):
    raw = sqlite3.connect(live)
    now = time.time()
    for i in range(live_audit.MIN_REQUESTS):
        raw.execute("INSERT INTO gateway_requests (at, alias, lane, error_class) VALUES (?, 'sohot-code', 'code', ?)",
                    (now - i, "APIError" if i % 2 else ""))
    raw.commit()
    raw.close()
    check = _checks(live_audit.audit(live))["gateway_errors"]
    assert not check["ok"] and "sohot-code" in check["detail"]


def test_a_few_errors_on_little_traffic_say_nothing(live):
    raw = sqlite3.connect(live)
    raw.execute("INSERT INTO gateway_requests (at, alias, lane, error_class) VALUES (?, 'sohot-code', 'code', 'X')",
                (time.time(),))
    raw.commit()
    raw.close()
    assert _checks(live_audit.audit(live))["gateway_errors"]["ok"]


def test_soh_audit_is_one_json_object_and_fails_on_a_failed_check(tmp_path, config, capsys):
    conn = ms.connect()
    try:
        _adopt(conn, _run(conn, tmp_path, False))
    finally:
        conn.close()
    gateway.write_served(config)
    assert cli.main(["audit", "--json"]) == 1
    got = json.loads(capsys.readouterr().out)
    assert got["ok"] is False and got["verb"] == "audit"
    assert {c["name"] for c in got["checks"]} == set(live_audit.CHECKS)


def test_soh_audit_prints_each_check(live, capsys):
    assert cli.main(["audit"]) == 0
    out = capsys.readouterr().out
    assert "ok   adoptions_pass_here" in out and out.rstrip().endswith("OK")


def test_the_audit_never_opens_the_store_through_the_migrating_connect(live, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the audit opened a read-write, migrating connection")
    monkeypatch.setattr(ms, "connect", refuse)
    assert live_audit.audit(live)["ok"]


def test_while_a_read_only_connection_is_lent_nothing_may_migrate(live):
    conn = live_audit.open_readonly(live)
    try:
        with ms.lend(conn):
            with pytest.raises(ms.ReadOnlyStore):
                ms.connect()
            with runs.store() as got:
                assert got is conn
        assert ms.lent() is None
    finally:
        conn.close()


def test_a_last_sweep_older_than_its_interval_fails(live, monkeypatch):
    """#625: the scheduled sweep stopped firing for a day and the audit said OK."""
    from harness import heartbeat
    monkeypatch.setattr(heartbeat, "clock", lambda: time.time() + 26 * 3600)
    check = _checks(live_audit.audit(live))["sweep_on_schedule"]
    assert not check["ok"] and "1d 2h" in check["detail"]
