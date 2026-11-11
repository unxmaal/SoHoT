"""A periodic unit or the OTLP receiver meeting a store a deploy has moved ahead: one named line, no traceback. #1799."""
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request

import pytest

from harness import cli, delegations, monitor, otel, paths, store_ahead, usage
from harness import memory_store as ms
from harness.memory_store.migrations import NewerStore
from harness.memory_store.schema import SCHEMA_VERSION

# A store stamped one schema ahead of this code is a SQLite file here.
pytestmark = pytest.mark.sqlite_store

SERVICES = {
    "watchdog": ["watchdog"],
    "delegations": ["delegated", "--close"],
    "sweep-check": ["sweep-check", "--notify"],
}


def _ahead(open_deploy_at=None):
    """This home's store, one schema ahead of this code, optionally with an open deploys row."""
    path = ms.db_path()
    ms.connect(path).close()
    conn = sqlite3.connect(path)
    if open_deploy_at is not None:
        conn.execute("INSERT INTO deploys (sha, stage, started_at, outcome) VALUES ('abc', 'migrating', ?, '')",
                     (open_deploy_at,))
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION + 1),))
    conn.commit()
    conn.close()
    return path


def _release(monkeypatch, linked: str):
    """This code runs from releases/7-old; the deploy link names releases/<linked>."""
    root = paths.home() / "releases" / "7-old"
    root.mkdir(parents=True)
    (paths.home() / "releases" / linked).mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "REPO", root)
    monkeypatch.setattr(paths, "deploy_link", lambda: paths.home() / "releases" / linked)
    return root


@pytest.fixture
def _quiet_units(monkeypatch):
    from harness import sweep_check
    monkeypatch.setenv("SOHOT_PURPOSE", "watchdog")
    monkeypatch.setattr(sweep_check, "check", lambda held=None: {"verdict": sweep_check.RUNNING, "line": "running"})


@pytest.mark.parametrize("unit", sorted(SERVICES))
def test_a_unit_on_a_superseded_release_skips_its_cycle_quietly(unit, monkeypatch, capsys, _no_real_notifier,
                                                                 _quiet_units):
    _ahead()
    _release(monkeypatch, "8-new")
    assert cli.main(SERVICES[unit]) == 0
    out = capsys.readouterr()
    assert "store ahead, waiting for reload" in out.out and "7-old" in out.out
    assert "Traceback" not in out.out + out.err and out.err == ""
    assert _no_real_notifier == [] and not monitor.alerts_path().exists()


@pytest.mark.parametrize("unit", sorted(SERVICES))
def test_a_unit_still_linked_while_a_deploy_runs_waits_for_its_reload(unit, monkeypatch, capsys, _no_real_notifier,
                                                                     _quiet_units):
    _ahead(open_deploy_at=time.time() - 60)
    _release(monkeypatch, "7-old")
    assert cli.main(SERVICES[unit]) == 0
    out = capsys.readouterr()
    assert "the running deploy's switch reloads this unit" in out.out and out.err == ""
    assert _no_real_notifier == []


@pytest.mark.parametrize("opened", [None, -store_ahead.RUNNING_FOR_S - 60], ids=["no-deploy", "deploy-died-unsettled"])
def test_a_stale_link_is_said_loudly_in_one_line(opened, monkeypatch, capsys, _quiet_units):
    _ahead(open_deploy_at=None if opened is None else time.time() + opened)
    _release(monkeypatch, "7-old")
    assert cli.main(["watchdog"]) == 1
    out = capsys.readouterr()
    assert "store ahead of the linked release" in out.err and "no deploy is running" in out.err
    assert "Traceback" not in out.err and out.err.count("\n") == 1


def test_a_checkout_behind_the_store_names_both_schemas(monkeypatch, capsys, _quiet_units):
    _ahead()
    monkeypatch.setattr(paths, "deploy_link", lambda: pytest.fail("a checkout never asks the deploy link"))
    assert cli.main(["watchdog"]) == 1
    err = capsys.readouterr().err
    assert f"schema {SCHEMA_VERSION + 1}, this code speaks {SCHEMA_VERSION}" in err and "Traceback" not in err


def test_a_schema_refusal_wrapped_as_a_gpu_refusal_is_the_same_outcome(monkeypatch, capsys):
    from harness import exclusive
    _ahead()
    _release(monkeypatch, "8-new")

    def refused(a):
        try:
            raise NewerStore(f"discovery.db is schema {SCHEMA_VERSION + 1}, this code speaks {SCHEMA_VERSION}.")
        except NewerStore as exc:
            raise exclusive.StoreDown("watchdog refused: the store answers at another schema") from exc
    monkeypatch.setattr(cli, "_watchdog", refused)
    assert cli.main(["watchdog"]) == 0
    assert "store ahead, waiting for reload" in capsys.readouterr().out


def test_an_outage_is_still_an_outage(monkeypatch, capsys):
    from harness import exclusive

    def down(a):
        raise exclusive.StoreDown("the store is unreachable")
    monkeypatch.setattr(cli, "_watchdog", down)
    assert cli.main(["watchdog"]) == 1
    assert "the store is unreachable" in capsys.readouterr().err


def _post(port: int) -> tuple[int, dict, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/logs", data=b"{}",
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read()), r.headers.get("Retry-After", "")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()), exc.headers.get("Retry-After", "")


def _ahead_sink(**rows):
    raise NewerStore(f"discovery.db is schema {SCHEMA_VERSION + 1}, this code speaks {SCHEMA_VERSION}. "
                     f"Refusing to touch a newer store.")


@pytest.mark.parametrize("kind", [store_ahead.SUPERSEDED, store_ahead.RELOAD])
def test_the_otlp_receiver_answers_retry_later_and_restarts_only_when_superseded(kind, monkeypatch, capsys):
    monkeypatch.setattr(store_ahead, "verdict", lambda *a, **k: kind)
    srv = otel.server("127.0.0.1", 0, sink=_ahead_sink)
    served = threading.Thread(target=srv.serve_forever, daemon=True)
    served.start()
    try:
        status, body, retry = _post(srv.server_address[1])
        assert status == 503 and retry == str(int(otel.RETRY_AFTER_S)) and "waiting for reload" in body["error"]
        served.join(timeout=5)
        if kind == store_ahead.SUPERSEDED:
            assert not served.is_alive(), "a superseded receiver keeps serving the old release"
        else:
            assert served.is_alive() and _post(srv.server_address[1])[0] == 503
    finally:
        if served.is_alive():
            srv.shutdown()
        srv.server_close()
    err = capsys.readouterr().err
    assert "Traceback" not in err and err.count("waiting for reload") == 1


def test_the_otlp_receiver_still_stores_what_a_current_store_takes():
    got = []
    srv = otel.server("127.0.0.1", 0, sink=lambda **rows: got.append(rows))
    served = threading.Thread(target=srv.serve_forever, daemon=True)
    served.start()
    try:
        assert _post(srv.server_address[1])[0] == 200 and got
    finally:
        srv.shutdown()
        srv.server_close()


def test_serving_paths_answer_while_the_store_is_ahead(monkeypatch):
    import contextlib

    def ahead():
        _ahead_sink()
    assert usage.record({"model": "m"}, connect=ahead) is False

    @contextlib.contextmanager
    def ledger():
        _ahead_sink()
        yield None
    monkeypatch.setattr(delegations, "ledger", ledger)
    assert delegations.request({"model": "m"}) is False
