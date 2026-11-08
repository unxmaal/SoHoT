"""While the store is down every gpu lease acquirer refuses, naming why; install and deploy run under the flock. #1648."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import delegate, deploy, exclusive, monitor, morning, router, serving
from harness import lane_probe as lp
from harness import workqueue as wq

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "scripts" / "with-gpu-lock"
REASON = "the store is unreachable"
LOOPBACK = serving.Route("http://127.0.0.1:4000", "sohot-code", {})


@pytest.fixture(autouse=True)
def alerts(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    said = []
    monkeypatch.setattr(exclusive, "_alert", lambda kind, message: said.append((kind, message)))
    return said


@pytest.fixture
def down(monkeypatch):
    up = exclusive._conn

    def refused(*a, **k):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(exclusive, "_conn", refused)
    return up


@pytest.mark.parametrize("kind", ["eval", "image", "external", "ramp", "chaos"])
def test_a_held_gpu_kind_is_refused_naming_the_store_and_takes_no_flock(down, kind):
    with pytest.raises(exclusive.StoreDown, match=REASON) as got:
        with exclusive.held(kind):
            pytest.fail("ran with no gpu lease")
    assert str(got.value).startswith(f"{kind} refused")
    assert not exclusive._taken(exclusive.lock_path())


def test_a_no_wait_hold_is_refused_too(down):
    with pytest.raises(exclusive.StoreDown, match=REASON):
        with exclusive.try_held("chaos"):
            pytest.fail("try_held ran with no gpu lease")
    with pytest.raises(exclusive.StoreDown, match=REASON):
        with exclusive.gpu_now("router release"):
            pytest.fail("gpu_now ran with no gpu lease")


def test_install_holds_the_flock_alone_and_records_no_refusal(down, alerts):
    said = []
    with exclusive.held("install", announce=said.append):
        assert exclusive._taken(exclusive.lock_path())
    assert "holds the local lock only" in said[0]
    assert exclusive.refusal() == {} and alerts == []


def test_the_first_refusal_is_alerted_once_shown_by_monitor_status_and_ends_at_the_next_connect(
        down, alerts, monkeypatch):
    for kind in ("eval", "external"):
        with pytest.raises(exclusive.StoreDown):
            with exclusive.held(kind):
                pass
    assert [k for k, _ in alerts] == ["gpu-refused"] and REASON in alerts[0][1]
    assert exclusive.refusal()["who"] == "eval"
    shown = monitor.status(which=lambda name: None)["problems"]
    assert any(p.startswith("gpu work refused since") and REASON in p for p in shown)
    monkeypatch.setattr(exclusive, "_conn", down)
    assert exclusive.gpu_leases() == 0
    assert exclusive.refusal() == {} and [k for k, _ in alerts] == ["gpu-refused", "recovered"]
    assert not any("gpu work refused" in p for p in monitor.status(which=lambda name: None)["problems"])


def test_the_worker_starts_no_gpu_job_and_says_why(down, capsys):
    job = wq.add([sys.executable, "-c", "pass"], title="gpu job")
    assert wq.run_pending(popen=lambda *a, **k: pytest.fail("ran a gpu job with no gpu lease")) == []
    assert wq.get(job["id"])["state"] == wq.PENDING
    out = capsys.readouterr().out
    assert "worker refused" in out and REASON in out


def test_a_delegation_is_refused_naming_the_store(down, monkeypatch):
    monkeypatch.setattr(delegate, "upstream", lambda where, config=None: ("http://127.0.0.1:8082", "m"))
    with pytest.raises(delegate.Refused, match=REASON):
        delegate._gate(LOOPBACK)
    with pytest.raises(delegate.Refused, match=REASON):
        delegate._turn(LOOPBACK, "code")
    with pytest.raises(delegate.Refused, match=REASON):
        morning._ask("headline")


def test_a_lane_probe_is_skipped_naming_the_store(down, monkeypatch, tmp_path):
    monkeypatch.setattr(delegate, "upstream", lambda where, config=None: ("http://127.0.0.1:8082", "m"))
    monkeypatch.setattr(serving, "engine_at", lambda base, **k: serving.LLAMACPP)
    row, request = lp.prepare("code", lp.Sender(tmp_path), resolve=lambda lane: ("spec", LOOPBACK),
                              resident=lambda where: pytest.fail("asked the server with no gpu lease"))
    assert request is None and row["outcome"] == lp.SKIPPED and REASON in row["reason"]


def test_a_router_release_keeps_its_models_naming_the_store(down, monkeypatch):
    monkeypatch.setattr(router, "_get", lambda path: {"data": [{"id": "M", "status": {"value": "loaded"}}]})
    monkeypatch.setattr(router, "_post", lambda path, body: pytest.fail("unloaded with no gpu lease"))
    said = []
    assert router.release(["M"], "x", keep=set(), say=said.append) == []
    assert REASON in said[0]


def _down_home(tmp_path) -> dict:
    home = tmp_path / "home"
    (home / "discovery.db").mkdir(parents=True)
    (home / "queue").mkdir()
    # A refusal already stands, so the child sends no desktop alert.
    (home / "queue" / exclusive.REFUSED).write_text("{}", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != exclusive.HELD_ENV}
    return {**env, "LOCALHARNESS_HOME": str(home), "LOCALHARNESS_STORE": "sqlite"}


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX script")
def test_with_gpu_lock_refuses_naming_the_store_and_runs_nothing(tmp_path):
    ran = tmp_path / "ran"
    got = subprocess.run([str(HELPER), sys.executable, "-c", f"open({str(ran)!r}, 'w')"],
                         env=_down_home(tmp_path), capture_output=True, text=True, timeout=120)
    assert got.returncode != 0 and "external refused" in got.stderr and REASON in got.stderr
    assert not ran.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX script")
def test_with_gpu_lock_repair_runs_under_the_flock_while_the_store_is_down(tmp_path):
    probe = (f"import sys; sys.path.insert(0, {str(REPO)!r}); from harness import exclusive as e; "
             "sys.exit(7 if e._taken(e.lock_path()) else 3)")
    got = subprocess.run([str(HELPER), "--repair", sys.executable, "-c", probe],
                         env=_down_home(tmp_path), capture_output=True, text=True, timeout=120)
    assert got.returncode == 7, got.stderr
    assert "holds the local lock only" in got.stderr


def test_install_reinstall_and_deploy_go_through_the_repair_hold():
    text = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    assert 'with-gpu-lock" --repair "$0" install' in text
    assert 'with-gpu-lock" --repair "$0" reinstall' in text
    assert deploy.Steps().install == ["bash", "scripts/launchd.sh", "reinstall"]
