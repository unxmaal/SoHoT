"""#1899: a gateway switch killed mid-way is settled and started again by the worker, once per adoption, then alerted."""
import subprocess
import sys
import types

import pytest
import yaml

from harness import completion, gateway, gateway_switch as gs, gateway_switch_state as st
from harness import memory_store as ms
from harness import paths, proc_identity
from harness import workqueue as wq
from tests.test_gateway_switch import STEM, Clock, adopt_for, config, gw  # noqa: F401

posix = pytest.mark.skipif(sys.platform == "win32", reason="proc_identity cannot judge a pid on Windows")
REQUESTED_AT = 5.0


class Died(BaseException):
    """The switch process killed mid-move: nothing in it runs after this."""


def _killed() -> dict:
    """The identity of a process that ran and was SIGKILLed: the switch process gone with no chance to clean up."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    ident = proc_identity.identity(child.pid)
    child.kill()
    child.wait()
    return ident


def _claim(requested_at=REQUESTED_AT, **ident):
    conn = ms.connect()
    try:
        return st.claim(conn, requested_at=requested_at, config=str(gateway.served_path()), **ident)
    finally:
        conn.close()


def _row(rid):
    conn = ms.connect()
    try:
        return st.get(conn, rid)
    finally:
        conn.close()


def _die():
    raise Died()


def _crash(gw, config, requested_at=REQUESTED_AT, ident=None):
    """An adoption whose switch wrote the new served config, asked for its restart and was killed there."""
    if not gateway.served_path(config).exists():
        gateway.write_served(config)
    before = gateway.served_path(config).read_text(encoding="utf-8")
    gw.models = gateway.load(gateway.served_path(config))["model_list"]
    adopt_for("code", f"llamacpp:{STEM}")
    rid = _claim(requested_at, **(ident or _killed()))
    clock = Clock()
    with pytest.raises(Died):
        gs.switch(base=gw.base, restart=_die, idle_s=1, max_wait_s=5, poll_s=1, clock=clock.now,
                  sleep=clock.sleep, advance=gs._advance(rid))
    return rid, before


@pytest.fixture
def started(monkeypatch):
    got = []
    monkeypatch.setattr(gs, "respawn", lambda requested_at: got.append(requested_at), raising=False)
    return got


@pytest.fixture
def alerts(monkeypatch):
    got = []
    monkeypatch.setattr(gs, "_alert", got.append, raising=False)
    return got


@posix
def test_a_switch_killed_mid_way_is_repaired_by_the_worker_without_a_new_adoption(gw, config, started, alerts,
                                                                                    monkeypatch):
    monkeypatch.setattr(completion, "DEFAULT_GATEWAY", gw.base)
    rid, before = _crash(gw, config)
    path = gateway.served_path(config)
    assert _row(rid)["state"] == st.RESTARTING and path.read_text(encoding="utf-8") != before
    wq.serve(forever=False, gate_fn=lambda: (False, "held by the test"))
    row = _row(rid)
    assert (row["state"], row["reason"], row["live"]) == (st.FAILED, st.DIED, None)
    assert path.read_text(encoding="utf-8") == before
    assert started == [REQUESTED_AT] and alerts == []


@posix
def test_a_respawned_switch_that_dies_too_is_settled_and_alerted_never_started_a_third_time(gw, config, started,
                                                                                            alerts):
    old = lambda want: "serves the old model"  # noqa: E731
    first, _ = _crash(gw, config)
    got = gs.repair(serving=old)
    assert (got["switch"], got["respawned"], got["alerted"]) == (first, True, "")
    second, before = _crash(gw, config)
    got = gs.repair(serving=old)
    assert (_row(second)["state"], _row(second)["reason"], _row(second)["live"]) == (st.FAILED, st.DIED, None)
    assert gateway.served_path(config).read_text(encoding="utf-8") == before
    assert got["respawned"] is False and started == [REQUESTED_AT]
    assert len(alerts) == 1 and alerts[0] == got["alerted"]
    assert "died 2 times" in alerts[0] and "until the next adoption" in alerts[0]
    assert gs.repair(serving=old) is None and started == [REQUESTED_AT] and len(alerts) == 1


@posix
def test_each_adoption_gets_its_own_respawn(gw, config, started, alerts):
    old = lambda want: "serves the old model"  # noqa: E731
    _crash(gw, config, requested_at=5.0)
    gs.repair(serving=old)
    _crash(gw, config, requested_at=9.0)
    gs.repair(serving=old)
    assert started == [5.0, 9.0] and alerts == []


def test_a_switch_whose_process_lives_is_left_alone(gw, config, started, alerts):
    rid, _ = _crash(gw, config, ident=st.me())
    assert gs.repair() is None
    assert _row(rid)["state"] == st.RESTARTING and started == [] and alerts == []


def test_a_switch_whose_process_cannot_be_judged_is_left_alone(gw, config, started, alerts):
    rid, _ = _crash(gw, config, ident={"pid": 1, "pgid": 1, "started": "1.0"})
    assert gs.repair(alive=lambda row: None) is None
    assert _row(rid)["state"] == st.RESTARTING and started == []


@posix
def test_a_dead_switch_the_gateway_already_serves_is_finished_and_not_started_again(gw, config, started, alerts):
    rid, _ = _crash(gw, config)
    gw.models = None
    got = gs.repair(serving=lambda want: gs.not_serving(gw.base, want))
    assert (got["state"], got["reason"], got["respawned"]) == (st.SERVING, st.FINISHED, False)
    assert started == [] and alerts == []


@posix
def test_a_dead_switch_whose_adoption_was_withdrawn_is_not_started_again(gw, config, started, alerts, monkeypatch):
    rid, _ = _crash(gw, config)
    monkeypatch.setattr(gs, "pending", lambda config=None: False)
    got = gs.repair(serving=lambda want: "serves the old model")
    assert (got["state"], got["reason"], got["respawned"]) == (st.FAILED, st.DIED, False)
    assert started == [] and alerts == []


@posix
def test_a_switch_that_raised_is_not_started_again(gw, config, started, alerts):
    rid, _ = _crash(gw, config)
    conn = ms.connect()
    try:
        gs.settle(conn, _row(rid), st.RAISED, serving=lambda want: "serves the old model")
    finally:
        conn.close()
    assert gs.repair() is None and started == [] and alerts == []


@posix
def test_a_switch_with_no_requested_time_alerts_rather_than_starting_unbounded(gw, config, started, alerts):
    rid, _ = _crash(gw, config)
    conn = ms.connect()
    try:
        conn.execute("UPDATE gateway_switch_runs SET requested_at = NULL WHERE id = ?", (rid,))
        conn.commit()
    finally:
        conn.close()
    got = gs.repair(serving=lambda want: "serves the old model")
    assert got["respawned"] is False and started == [] and len(alerts) == 1


@posix
def test_only_the_scheduler_repairs_a_switch(gw, config, started, alerts):
    rid, _ = _crash(gw, config)
    (paths.home() / "role").write_text("node\n", encoding="utf-8")
    assert gs.repair(serving=lambda want: "serves the old model") is None
    assert _row(rid)["state"] == st.RESTARTING and started == []
    (paths.home() / "role").write_text("scheduler\n", encoding="utf-8")
    assert gs.repair(serving=lambda want: "serves the old model")["respawned"] is True


def test_no_role_file_is_the_scheduler_as_launchd_sh_defaults_it():
    assert paths.role() == paths.SCHEDULER


def test_respawn_starts_no_switch_outside_the_live_home(monkeypatch):
    spawned = []
    monkeypatch.setattr(gs, "spawn", lambda **kw: spawned.append(kw))
    with pytest.raises(OSError, match="not the live home"):
        gs.respawn(REQUESTED_AT)
    assert spawned == []
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    gs.respawn(REQUESTED_AT)
    assert spawned == [{"requested_at": REQUESTED_AT}]


def test_the_alert_names_the_gateway_switch_service(monkeypatch):
    from harness import monitor
    sent = []
    monkeypatch.setattr(monitor, "alert", lambda kind, environ: sent.append((kind, environ)))
    gs._alert("it died")
    assert sent == [("service", {"MONIT_SERVICE": "gateway-switch", "MONIT_EVENT": st.GAVE_UP,
                                 "MONIT_DESCRIPTION": "it died"})]


def test_a_failing_repair_never_stops_the_worker(monkeypatch, capsys):
    def boom():
        raise RuntimeError("store gone")
    monkeypatch.setattr(gs, "repair", boom)
    wq.deploy_turn(5.0)
    assert "gateway switch repair failed: store gone" in capsys.readouterr().out


def test_the_worker_repairs_while_a_job_runs(monkeypatch):
    seen = []
    monkeypatch.setattr(gs, "repair", lambda: seen.append(1))
    wq.add(["true"], title="t", cwd=str(paths.home()))
    wq.run_pending(popen=lambda argv, **kw: types.SimpleNamespace(returncode=0), clock=lambda: 5.0)
    assert seen


@posix
def test_a_switch_that_cannot_be_started_again_alerts(gw, config, alerts):
    def refuse(requested_at):
        raise OSError("no fork")
    _crash(gw, config)
    got = gs.repair(serving=lambda want: "serves the old model", start=refuse)
    assert got["respawned"] is False and len(alerts) == 1 and "no fork" in alerts[0]


@posix
def test_the_worker_says_what_it_settled(gw, config, started, capsys, monkeypatch):
    monkeypatch.setattr(completion, "DEFAULT_GATEWAY", gw.base)
    rid, _ = _crash(gw, config)
    gs.turn()
    out = capsys.readouterr().out
    assert f"gateway switch {rid} settled failed (died); started again" in out


@posix
def test_a_dead_switch_whose_config_another_writer_changed_is_not_started_again(gw, config, started, alerts):
    rid, _ = _crash(gw, config)
    path = gateway.served_path(config)
    cfg = gateway.load(path)
    for entry in cfg["model_list"]:
        if entry["model_name"] == gateway.LANE_ALIAS.format("code"):
            entry["litellm_params"]["model"] = "openai/by-hand"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert gs.pending(config)
    got = gs.repair(serving=lambda want: "serves the old model")
    assert (got["state"], got["reason"], got["respawned"]) == (st.FAILED, st.SUPERSEDED, False)
    assert started == [] and alerts == []
