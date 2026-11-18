"""#2064: every queue pause records who took it and why; one blocking a deploy re-alerts, and an old owner pause is named."""
import json
import os
import time

import pytest

from harness import cli, contention, deploy, monitor, morning, pressure, queue_hold, queue_pause, workqueue as wq
from harness import memory_store as ms
from tests.test_deploy_wait_1672 import _deploy, warn  # noqa: F401 - the fixture is used by name

DAY = 86400.0
SESSION = "abcdef0123456789"


@pytest.fixture
def agent_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    monkeypatch.setenv("AI_AGENT", "claude-code_agent")
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")


def _cuts(knob: str) -> list:
    conn = ms.connect()
    try:
        return [r[0] for r in conn.execute("SELECT knob FROM limit_cuts WHERE knob = ?", (knob,))]
    finally:
        conn.close()


def _alerts(monkeypatch) -> list:
    sent = []
    monkeypatch.setattr(deploy, "_alert_script", lambda message, event="waiting": sent.append((event, message)))
    return sent


def test_the_cli_refuses_a_pause_with_no_reason(capsys):
    assert cli.main(["jobs", "pause", "--json"]) != 0
    assert not queue_pause.paused(), "a refused pause leaves the queue running"


def test_a_cli_pause_records_who_took_it_and_why(capsys, agent_env):
    assert cli.main(["jobs", "pause", "--reason", "checking the tts lane", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is True
    body = queue_pause.body()
    by = queue_hold.by_of(body)
    assert by["pid"] == os.getpid() and by["ppid"] == os.getppid() and by["argv"]
    assert by["session"] == SESSION and by["agent"] == "claude-code_agent" and by["subagent"] == "1"
    assert queue_hold.holder_of(body) is None, "a CLI pause is the owner's, never lifted by its process ending"
    assert queue_hold.reason(body) == "checking the tts lane"
    ok, why = wq.gate(sample=lambda: pressure.Pressure(level=pressure.NORMAL))
    assert not ok and "checking the tts lane" in why and "session abcdef01" in why and why.endswith("(soh jobs resume)")


def test_every_other_pause_records_its_caller_and_flags_a_missing_reason():
    queue_pause.pause()
    body = queue_pause.body()
    assert queue_hold.by_of(body)["pid"] == os.getpid()
    assert queue_hold.reason(body) == queue_hold.NO_REASON
    monitor.pause_all("monit: system_data space free 20 GB")
    assert queue_hold.reason(queue_pause.body()) == "monit: system_data space free 20 GB"


def test_a_pause_blocking_a_deploy_alerts_again_each_interval_until_it_is_lifted(warn, monkeypatch):  # noqa: F811
    warn["p"] = pressure.NORMAL
    sent = _alerts(monkeypatch)
    now = time.time()
    _deploy(now - contention.DEPLOY_ALERT_S - 60)
    queue_pause.pause("looking at a lane")
    assert deploy.watch_wait(now) is not None and len(sent) == 1
    assert sent[0][0] == "waiting" and "looking at a lane" in sent[0][1]
    assert deploy.watch_wait(now + 3600) is None and len(sent) == 1
    assert deploy.watch_wait(now + contention.PAUSE_REALERT_S + 1) is not None and len(sent) == 2
    assert deploy.watch_wait(now + contention.PAUSE_REALERT_S + 3600) is None and len(sent) == 2
    assert _cuts("deploy_pause_realert") == ["deploy_pause_realert"]
    queue_pause.resume()
    assert deploy.watch_wait(now + 3 * contention.PAUSE_REALERT_S) is None and len(sent) == 2


def test_a_wait_alerted_for_another_reason_alerts_again_once_a_pause_holds_it(warn, monkeypatch):  # noqa: F811
    sent = _alerts(monkeypatch)
    monkeypatch.setattr(contention, "DEPLOY_PRESSURE_S", 10 * DAY)
    now = time.time()
    _deploy(now - contention.DEPLOY_ALERT_S - 60)
    assert deploy.watch_wait(now) is not None and "memory pressure" in sent[0][1]
    assert deploy.watch_wait(now + 60) is None and len(sent) == 1
    queue_pause.pause("on hold")
    assert deploy.watch_wait(now + 120) is not None and "on hold" in sent[1][1]


def test_an_old_owner_pause_with_a_deploy_pending_raises_a_distinct_blocked_alert(warn, monkeypatch, agent_env):  # noqa: F811
    warn["p"] = pressure.NORMAL
    sent = _alerts(monkeypatch)
    now = time.time() + 2 * DAY
    job = _deploy(now - 3 * DAY)
    assert cli.main(["jobs", "pause", "--reason", "debugging the gateway"]) == 0
    assert deploy.watch_wait(now) is not None
    event, line = sent[0]
    assert event == "blocked" and line.startswith("deploys blocked 2.0 days by a pause from `")
    assert "session abcdef01" in line and "(debugging the gateway)" in line and f"deploy job {job['id']}" in line
    assert _cuts("deploy_pause_stale") == ["deploy_pause_stale"]
    w = deploy.wait(ms.connect(), now)
    r = {"deploys": [], "sweep": {"loop": None}, "deploy": {}, "stale": [], "ci": {}, "watchdog": [], "incidents": [],
         "deploy_wait": w}
    assert line in morning.needs(r), "the morning brief names the pause until it is lifted"


def test_a_pause_younger_than_the_stale_knob_or_held_by_a_process_is_no_blocked_alert(warn, monkeypatch):  # noqa: F811
    warn["p"] = pressure.NORMAL
    now = time.time() + contention.PAUSE_STALE_S - 3600
    w = {"job": "0007", "sha": "f" * 40, "since": now - DAY, "first": 7, "waited": DAY, "why": "paused", "held": False}
    queue_pause.pause("young")
    assert deploy.blocked_line({**w, "pause": queue_pause.body()}, now)[0] == "waiting"
    queue_pause.pause("held", holder=os.getpid())
    assert deploy.blocked_line({**w, "pause": queue_pause.body()}, now + DAY)[0] == "waiting"


def test_a_pause_written_before_2064_reads_as_from_an_unrecorded_caller(warn, monkeypatch):  # noqa: F811
    now = time.time()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 3 * DAY))
    w = {"job": "0007", "sha": "f" * 40, "since": now - 3 * DAY, "first": 7, "waited": 3 * DAY, "why": "paused",
         "held": False, "pause": stamp}
    event, line = deploy.blocked_line(w, now)
    assert event == "blocked"
    assert line.startswith("deploys blocked 3.0 days by a pause from an unrecorded caller (no holder line) "
                           "(no reason given)")


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/queue_pause.py:body:except")
def test_an_empty_pause_flag_is_a_pause_and_still_alerts_again(warn, monkeypatch):  # noqa: F811
    warn["p"] = pressure.NORMAL
    sent = _alerts(monkeypatch)
    now = time.time()
    _deploy(now - contention.DEPLOY_ALERT_S - 60)
    assert queue_pause.body() is None
    queue_pause._pause_flag().write_text("", encoding="utf-8")
    assert queue_pause.body() == ""
    assert deploy.watch_wait(now) is not None and deploy.watch_wait(now + contention.PAUSE_REALERT_S + 1) is not None
    assert len(sent) == 2


# --- monit: nothing has run for queue_stale_alert while work is due ------------------------------------------------

def _stale(now):
    from harness import queue_stale
    with wq._store() as c:
        return queue_stale.stale(c, now)


def test_a_planted_stale_queue_fires_the_monit_check_and_a_fresh_one_stays_quiet(warn, monkeypatch):  # noqa: F811
    from harness import queue_stale
    from tests.test_deploy_wait_1672 import _set
    now = time.time()
    assert _stale(now) == "", "nothing due: quiet"
    ran = wq.add(["true"], title="ran")
    _set(ran, state=wq.DONE, started_at=now - 3 * DAY, finished_at=now - 3 * DAY + 60)
    job = _deploy(now - 2 * DAY)
    queue_pause.pause("forgotten")
    said = _stale(now)
    assert said.startswith("nothing has run for 48.0 h with 1 due job(s) pending (deploy)")
    assert f"deploy job {job['id']} among them" in said and "forgotten" in said
    assert _cuts("queue_stale_alert") == ["queue_stale_alert"]
    _set(ran, finished_at=now - queue_stale.QUEUE_STALE_S + 60)
    assert _stale(now) == "", "a job finished inside the knob: the queue moves"
    _set(ran, finished_at=now - 3 * DAY)
    from harness import deploy as d
    d.record_path(1).write_text("{}", encoding="utf-8")
    assert _stale(now) == "", "a deploy record written inside the knob: deploys move"


def test_work_queued_inside_the_knob_or_not_yet_due_is_not_stale(warn):  # noqa: F811
    from harness import queue_stale
    from tests.test_deploy_wait_1672 import _set
    now = time.time()
    job = wq.add(["true"], title="new")
    _set(job, created_at=now - queue_stale.QUEUE_STALE_S + 60)
    assert _stale(now) == ""
    _set(job, created_at=now - 2 * DAY, not_before=now + 3600)
    assert _stale(now) == "", "a job not yet due waits on purpose"
    _set(job, not_before=None)
    assert _stale(now).startswith("nothing has run for 48.0 h")


def test_the_monit_script_exits_1_on_a_stale_queue_and_0_on_a_fresh_one(warn, monkeypatch):  # noqa: F811
    from harness import queue_stale
    from tests.test_deploy_wait_1672 import _set
    job = wq.add(["true"], title="stuck")
    assert queue_stale.main() == 0
    _set(job, created_at=time.time() - 2 * DAY)
    assert queue_stale.main() == 1


def test_monit_runs_the_queue_check_and_alerts_again_each_realert_interval(tmp_path):
    from tests.test_monitor_1485 import _spec
    text = monitor.render(_spec(tmp_path))
    check = text.split("check program queue_moves", 1)[1].split("\n\n", 1)[0]
    assert "monit-queue.sh" in check and 'monit-alert.sh queue-stale"' in check and "recovered" in check
    assert f"repeat every {monitor.cycles(contention.PAUSE_REALERT_S)} cycles" in check
    assert "queue-stale" in monitor.KINDS
