"""The status page's Needs-you band: each stopping condition planted in a scratch home, shown with its button, cleared by pressing it,
alerted once as it begins and once as it clears. #2134."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import types

import pytest

from harness import gateway_degraded, heartbeat, hold, monitor, needs_you, owner_actions as oa, queue_pause, status_page as sp
from harness import memory_store as ms
from harness import workqueue as wq

NOW = time.time()
HOST = {"host": "localhost:8899"}
NO_FEATURES = lambda conn, now, q: {"rows": []}  # noqa: E731
OK_BEAT = {"status": "finished", "started": NOW - 3600, "finished": NOW - 600, "rc": 0, "line": "last discovery loop finished"}
MAIN = "c" * 40


def _mon(rows=("gateway   OK   Process",), running=True):
    return lambda: {"installed": True, "running": running, "current": True, "webhook": True, "problems": [],
                    "summary": ["Service Name   Status   Type", *rows]}


def fake_git(argv):
    return {"rev-parse": ("b" * 40 if "HEAD" in argv else MAIN) if "rev-parse" in argv else "", "rev-list": "1"}.get(
        next((w for w in ("rev-parse", "rev-list") if w in argv), ""), "")


def gather(tmp_path, now=NOW, **kw):
    (tmp_path / "checkout" / ".git").mkdir(parents=True, exist_ok=True)
    args = {"connect": ms.connect, "beat": OK_BEAT, "where": tmp_path / "checkout", "mon": _mon(), "features": NO_FEATURES,
            "git": fake_git, "home": tmp_path,
            "health": lambda lane: {"lane": lane, "spec": "m", "base": "http://127.0.0.1:1", "generating": True, "why": ""},
            "reach": lambda since, now: [], "flow": lambda now: {"available": False, "why": "no transcripts"}}
    args.update(kw)
    return sp.gather(now, **args)


def keys(r):
    return [c["key"] for c in r["needs_you"]]


def cond(r, key):
    return next(c for c in r["needs_you"] if c["key"] == key)


def at(text):
    return time.mktime(time.strptime(text, "%Y-%m-%d %H:%M"))


def with_conn(fn):
    conn = ms.connect()
    try:
        return fn(conn)
    finally:
        conn.close()


def plant_job(tmp_path, state, title="sweep step", started=None, finished=None, note="boom", rc=1):
    def go(conn):
        job = wq.add(["true"], title=title, cwd=str(tmp_path), conn=conn)
        conn.execute("UPDATE jobs SET state = ?, started_at = ?, finished_at = ?, note = ?, rc = ? WHERE id = ?",
                     (state, started, finished, note, rc, int(job["id"])))
        conn.commit()
        return job["id"]
    return with_conn(go)


@pytest.fixture
def client(monkeypatch, tmp_path):
    srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")
    from starlette.testclient import TestClient
    monkeypatch.setattr(sp, "cached", lambda: gather(tmp_path))
    app = srv.SERVER.streamable_http_app(transport_security=srv.transport_security("0.0.0.0", 8899), host="0.0.0.0")
    return TestClient(app)


def band(client):
    page = client.get("/status", headers=HOST).text
    section = re.search(r"<section class='needs.*?</section>", page, re.S)
    return page, section.group(0) if section else ""


def forms(html):
    return [dict(re.findall(r"name='(\w+)' value='([^']*)'", f)) for f in re.findall(r"<form.*?</form>", html, re.S)]


def press(client, html, action, arg=""):
    """The two presses a button takes through POST /status/action: ask, then confirm."""
    form = next(f for f in forms(html) if f["action"] == action and f.get("arg", "") == arg)
    first = client.post("/status/action", data=form, headers=HOST)
    assert first.status_code == 200 and "Confirm" in first.text, first.text
    nonce = re.search(r"name='confirm' value='([^']+)'", first.text).group(1)
    done = client.post("/status/action", data={**form, "confirm": nonce}, headers=HOST)
    assert done.status_code == 200 and "Done" in done.text, done.text
    return done


def test_a_healthy_home_says_nothing_is_stopped(tmp_path, client):
    r = gather(tmp_path)
    assert r["needs_you"] == [] and r["banner"] == []
    page, section = band(client)
    assert "Nothing is stopped." in section and "class='need'" not in page
    assert needs_you.sync(r, tmp_path) == {"began": [], "cleared": [], "open": [], "at": r["generated"]}
    assert not [a for a in monitor.alerts(0, tmp_path) if a["kind"] == needs_you.KIND]


def test_a_benchmarks_hold_shows_who_and_why_and_its_button_releases_it(tmp_path, client):
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 7200))
    page, section = band(client)
    assert "Benchmarks held" in section and "owner: busy" in section and "stopped 2 h" in section
    press(client, section, "benchmarks_release")
    assert "hold-benchmarks" not in keys(gather(tmp_path))


def test_a_gpu_gate_hold_is_released_by_its_button(tmp_path, client):
    with_conn(lambda c: hold.hold(c, "owner: a video render", scope=hold.GPU, now=NOW - 600))
    _, section = band(client)
    assert "The GPU gate is held" in section and "a video render" in section
    press(client, section, "gate_release")
    assert gather(tmp_path)["needs_you"] == []


def test_a_paused_queue_names_who_and_resumes(tmp_path, client):
    queue_pause.pause("owner: looking into a failure")
    _, section = band(client)
    assert "The queue is paused" in section and "looking into a failure" in section
    press(client, section, "queue_resume")
    assert "queue-paused" not in keys(gather(tmp_path))


def test_a_failed_job_is_retried_and_the_retry_supersedes_it(tmp_path, client):
    job = plant_job(tmp_path, wq.FAILED, finished=NOW - 600, note="refused: needs more memory than the machine has")
    _, section = band(client)
    assert f"A job failed: job {job}" in section and "needs more memory" in section
    press(client, section, "job_retry", job)
    assert f"job-failed-{job}" not in keys(gather(tmp_path))
    assert any(j["state"] == wq.PENDING for j in wq.jobs())


def test_an_old_failure_and_a_failed_deploy_job_stay_out_of_the_band(tmp_path):
    plant_job(tmp_path, wq.FAILED, finished=NOW - needs_you.FAILED_WINDOW_S - 60)
    def deploy_job(c):
        j = wq.add(["true"], title="deploy x", cwd=str(tmp_path), kind="deploy", conn=c)
        c.execute("UPDATE jobs SET state = ?, finished_at = ? WHERE id = ?", (wq.FAILED, NOW - 60, int(j["id"])))
        c.commit()
    with_conn(deploy_job)
    assert not [k for k in keys(gather(tmp_path)) if k.startswith("job-")]


def test_a_job_past_every_watchdog_limit_is_stuck_and_cancels(tmp_path, client, monkeypatch):
    from harness import watchdog
    job = plant_job(tmp_path, wq.RUNNING, started=NOW - max(watchdog.long_run_limits().values()) - 3600, note="", rc=None)
    short = plant_job(tmp_path, wq.RUNNING, title="young", started=NOW - 600, note="", rc=None)
    _, section = band(client)
    assert f"A job is stuck: job {job}" in section and f"job {short}" not in section
    ran = []
    monkeypatch.setattr(oa, "run_verb", lambda argv, run=None: ran.append(argv) or {"rc": 0, "out": "cancelled"})
    press(client, section, "job_cancel", job)
    assert ran == [["jobs", "cancel", job]]


def test_a_paused_job_waits_out_its_grace_then_cancels(tmp_path, client):
    plant_job(tmp_path, wq.PAUSED, title="recent", started=NOW - 60, note="", rc=None)
    old = plant_job(tmp_path, wq.PAUSED, title="old", started=NOW - needs_you.PAUSED_GRACE_S - 60, note="memory pause", rc=None)
    _, section = band(client)
    assert f"A job is paused: job {old}" in section and "recent" not in section
    press(client, section, "job_cancel", old)
    assert f"job-paused-{old}" not in keys(gather(tmp_path))


def test_a_stalled_discovery_loop_is_restarted_from_the_band(tmp_path, client, monkeypatch):
    heartbeat._write({"state": "running", "pid": 2 ** 22 + 1, "started": NOW - 80000, "updated": NOW - 79000, "tier": "measure",
                      "step": 3, "total": 10, "lane": "code"})
    monkeypatch.setattr(sp, "cached", lambda: gather(tmp_path, beat=None))
    r = gather(tmp_path, beat=None)
    c = cond(r, "discovery-stalled")
    assert c["since"] < NOW - 70000 and "stalled" in c["why"]
    _, section = band(client)
    assert "The discovery loop has stalled" in section
    press(client, section, "discovery_on")
    after = cond(gather(tmp_path, beat=None), "discovery-stalled")
    assert after["fix"] == [] and "a restart is queued (job " in after["none"]
    assert with_conn(lambda c: __import__("harness.commands.loop_steps", fromlist=["x"]).waiting(c))


def test_deploys_failing_name_the_blocker_and_offer_deploy_now(tmp_path, client, monkeypatch):
    def plant(conn):
        mid = ms.remember_machine(conn)
        for i, out in enumerate(("rolled_back", "rolled_back")):
            conn.execute("INSERT INTO deploys (sha, machine_id, stage, outcome, started_at, detail) VALUES (?,?,?,?,?,?)",
                         (f"{i}" * 40, mid, out, out, NOW - 600 + i, "smoke before the switch: bash scripts/smoke.sh exited rc 1"))
        conn.commit()
    with_conn(plant)
    ran = []
    monkeypatch.setattr(oa, "run_verb", lambda argv, run=None: ran.append(argv) or {"rc": 0, "out": "queued"})
    _, section = band(client)
    assert "Deploys are failing" in section and "smoke" in section
    press(client, section, "deploy_now", MAIN)
    assert ran == [["deploy", "now", MAIN]]


def test_a_deploy_waiting_past_the_alert_bound_is_blocked_and_resumes_the_queue(tmp_path):
    from harness import contention
    queue_pause.pause("owner: busy")
    plant_job(tmp_path, wq.PENDING, title="deploy a4d931edd473", started=None, finished=None, note="", rc=None)
    with_conn(lambda c: c.execute("UPDATE jobs SET kind = 'deploy', output = ?, created_at = ? WHERE state = 'pending'",
                                  (MAIN, NOW - contention.DEPLOY_ALERT_S - 3600)) and c.commit())
    young = gather(tmp_path, now=NOW - contention.DEPLOY_ALERT_S - 1800)
    assert "deploy-blocked" not in keys(young)
    r = gather(tmp_path)
    c = cond(r, "deploy-blocked")
    assert "queue_resume" in [f["action"] for f in c["fix"]] and c["since"] < NOW - contention.DEPLOY_ALERT_S


def test_a_gateway_serving_the_base_config_is_marked_and_restarted(tmp_path, client, monkeypatch):
    gateway_degraded.mark("the store was not up when the gateway started", now=NOW - 90000)
    ran = []

    def restart(argv, run=None):
        ran.append(argv)
        gateway_degraded.clear()
        return {"rc": 0, "out": "restarted gateway"}
    monkeypatch.setattr(oa, "run_verb", restart)
    _, section = band(client)
    assert "The gateway serves no lane aliases" in section and "stopped 25 h" in section
    press(client, section, "unit_restart", "gateway")
    assert ran == [["unit-restart", "gateway"]] and "gateway-degraded" not in keys(gather(tmp_path))


def test_a_broken_unit_and_a_down_node_and_memory_pressure(tmp_path):
    rows = {"rows": [{"kind": "unit", "name": "mlx", "state": "broken", "by": "loaded, idle, last exit 1", "since": NOW - 3600}]}
    monitor.record({"at": NOW - 7200, "kind": "memory", "service": "memory_pressure", "description": "pressure warn for 600 s"}, tmp_path)
    r = gather(tmp_path, features=lambda c, n, q: rows, reach=lambda s, n: [{"node": "styx", "down_now": True, "down_s": 1800}])
    assert {"unit-mlx", "node-styx", "monit-memory_pressure"} <= set(keys(r))
    assert cond(r, "unit-mlx")["fix"] == [{"action": "unit_restart", "arg": "mlx"}]
    assert cond(r, "node-styx")["fix"] == [] and cond(r, "node-styx")["none"]
    assert cond(r, "monit-memory_pressure")["fix"] == [] and cond(r, "monit-memory_pressure")["since"] == NOW - 7200
    monitor.record({"at": NOW - 60, "kind": "recovered", "service": "memory_pressure", "description": "ok"}, tmp_path)
    assert "monit-memory_pressure" not in keys(gather(tmp_path))


def test_the_real_state_of_2026_11_25_a_base_config_gateway_for_26_hours(tmp_path):
    began, seen = at("2026-11-25 10:30"), at("2026-11-26 12:20")
    gateway_degraded.mark("store unreachable at login; served gateway/config.yaml with no sohot-<lane> aliases", now=began)
    r = gather(tmp_path, now=seen)
    c = cond(r, "gateway-degraded")
    assert c["since"] == began and c["fix"] == [{"action": "unit_restart", "arg": "gateway"}]
    assert "26 h" in sp.page(r, now=seen) or "stopped 26 h" in sp.page(r, now=seen)


def test_the_real_state_of_2026_11_26_a_stalled_discovery_loop_with_benchmarks_held(tmp_path):
    from harness import sweep_check
    held_at, seen = at("2026-11-25 16:06"), at("2026-11-26 12:20")
    with_conn(lambda c: hold.hold(c, "owner: busy", now=held_at))
    beat = {"status": "stalled", "started": at("2026-11-24 21:00"), "age_s": 21 * 3600, "rc": None,
            "line": "discovery loop stalled (code lane): no progress for 21h; process 2185 is gone", "finished": None}
    r = gather(tmp_path, now=seen, beat=beat)
    assert {"hold-benchmarks", "discovery-stalled"} <= set(keys(r))
    assert cond(r, "discovery-stalled")["since"] == seen - 21 * 3600
    assert [f["action"] for f in cond(r, "hold-benchmarks")["fix"]] == ["benchmarks_release"]
    quiet = sweep_check.check(now=seen, unit={"loaded": True, "state": "waiting", "runs": 3, "rc": 0, "pid": None},
                              beat=None, hours=[21], held="benchmarks held since 2026-11-25 16:06")
    assert quiet["verdict"] == sweep_check.HELD and not sweep_check.should_notify(quiet, "")
    got = needs_you.sync(r, tmp_path)
    assert "discovery-stalled" in got["began"] and "hold-benchmarks" in got["began"]


def test_each_condition_alerts_once_as_it_begins_and_once_as_it_clears(tmp_path):
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 60))
    sent = lambda: [a for a in monitor.alerts(0, tmp_path) if a["kind"] in (needs_you.KIND, monitor.RECOVERED)]  # noqa: E731
    r = gather(tmp_path)
    assert needs_you.sync(r, tmp_path)["began"] == ["hold-benchmarks"]
    assert needs_you.sync(r, tmp_path)["began"] == [] and len(sent()) == 1
    assert "Benchmarks held" in sent()[0]["description"] and "benchmarks release" in sent()[0]["description"]
    with_conn(lambda c: hold.release(c, NOW))
    clear = gather(tmp_path)
    assert needs_you.sync(clear, tmp_path)["cleared"] == [] and len(sent()) == 1
    assert needs_you.sync(clear, tmp_path)["cleared"] == ["hold-benchmarks"] and len(sent()) == 2
    assert sent()[1]["kind"] == monitor.RECOVERED and needs_you.sync(clear, tmp_path)["cleared"] == []
    assert len(sent()) == 2


def test_a_blink_in_one_pass_neither_clears_nor_re_alerts(tmp_path):
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 60))
    needs_you.sync(gather(tmp_path), tmp_path)
    gone = gather(tmp_path, now=NOW)
    gone["needs_you"], gone["stops"]["holds"]["rows"] = [], []
    assert needs_you.sync(gone, tmp_path)["cleared"] == []
    assert needs_you.sync(gather(tmp_path), tmp_path)["began"] == []
    assert len([a for a in monitor.alerts(0, tmp_path) if a["kind"] == needs_you.KIND]) == 1


def test_a_source_that_could_not_be_read_does_not_clear_what_it_showed(tmp_path):
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 60))
    needs_you.sync(gather(tmp_path), tmp_path)
    blind = gather(tmp_path, connect=lambda: (_ for _ in ()).throw(OSError("connection refused")))
    assert "hold-benchmarks" not in keys(blind) and "store-down" in keys(blind)
    for _ in range(3):
        assert needs_you.sync(blind, tmp_path)["cleared"] == []
    assert [a for a in monitor.alerts(0, tmp_path) if a["kind"] == monitor.RECOVERED] == []


def test_the_band_leaves_out_what_a_benchmarks_hold_explains(tmp_path):
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 60))
    r = gather(tmp_path, beat={**OK_BEAT, "rc": 1, "failure": "x", "overdue": "last discovery loop started 3 days ago"})
    assert keys(r) == ["hold-benchmarks"]


def test_a_forged_job_or_unit_is_refused(tmp_path):
    r = gather(tmp_path)
    for action, arg in (("job_retry", "0042"), ("job_cancel", "0042"), ("unit_restart", "launchd")):
        who = {"name": "p", "id": "p"}
        code, text = oa.press("p", {}, {"token": oa.token("p", who, NOW), "action": action, "arg": arg}, r, now=NOW, home=tmp_path,
                              run=lambda *a, **k: pytest.fail("a forged choice ran"))
        assert code == 400 and "does not offer" in text


def test_unit_restart_runs_launchd_restart_only_for_a_unit_it_installs():
    from harness import unit_restart
    ran = []
    run = lambda cmd, **kw: ran.append(cmd) or types.SimpleNamespace(returncode=0, stdout="", stderr="")  # noqa: E731
    assert unit_restart.restart("gateway", run=run, platform="darwin")["rc"] == 0
    assert ran[0][1:] == ["restart", "gateway"] and ran[0][0].endswith("scripts/launchd.sh")
    assert unit_restart.restart("rm -rf", run=run, platform="darwin")["rc"] == 2
    assert unit_restart.restart("gateway", run=run, platform="linux")["rc"] == 2 and len(ran) == 1


def test_monit_runs_the_pass_and_the_alert_kind_exists():
    text = monitor.render({"home": "/h", "scripts": "/s", "path": "/p", "data": "/d", "models": "", "models_floor_gib": 1,
                           "services": [], "store": False})
    assert "check program needs_you_pass" in text and "monit-needs-you.sh" in text and "then exec" in text
    assert needs_you.KIND in monitor.KINDS


def test_the_page_shows_its_age_and_reloads_without_a_meta_refresh_outside_noscript(tmp_path):
    page = sp.page(gather(tmp_path), now=NOW + 125)
    assert "id='age'" in page and "2 min old" in page and "data-gen=" in page and "data-every='60'" in page
    assert re.sub(r"<noscript>.*?</noscript>", "", page, flags=re.S).count("http-equiv") == 0
    assert "<noscript><meta http-equiv='refresh' content='60'></noscript>" in page


def _js(scenario: str) -> dict:
    from harness import status_view
    script = """
var timers=[],fetched=0,nextText='';
var age={textContent:'',className:''},live={dataset:{gen:'100',now:'200',every:'60'},innerHTML:'old',listeners:{},
 addEventListener:function(k,f){this.listeners[k]=f;}};
global.document={getElementById:function(i){return i==='live'?live:i==='age'?age:null;},activeElement:null};
global.setInterval=function(f,ms){timers.push([f,ms]);};
global.DOMParser=function(){this.parseFromString=function(t){return {getElementById:function(){return t==='bad'?null:{innerHTML:t,dataset:{gen:'400',now:'401'}};}};};};
global.fetch=function(){fetched++;return scenario==='down'?Promise.reject(new Error('x')):Promise.resolve({ok:true,text:function(){return Promise.resolve('fresh');}});};
global.location={href:'/status'};
%s
var tick=timers[0][0],refresh=timers[1][0];
var out=function(){console.log(JSON.stringify({fetched:fetched,html:live.innerHTML,age:age.textContent,cls:age.className,every:timers[1][1]}));};
if(scenario==='dirty'){live.listeners.change({target:{closest:function(){return {};}}});}
refresh();setImmediate(function(){setImmediate(out);});
""".replace("%s", status_view.REFRESH_JS)
    got = subprocess.run(["node", "-e", script.replace("scenario", repr(scenario))], capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout.splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the page's script")
def test_the_page_reloads_itself_but_not_over_a_pending_choice():
    clean = _js("clean")
    assert clean["fetched"] == 1 and clean["html"] == "fresh" and clean["every"] == 60000 and "old" in clean["age"]
    held = _js("dirty")
    assert held["fetched"] == 0 and held["html"] == "old" and "refresh waits on your choice" in held["age"]
    down = _js("down")
    assert down["html"] == "old" and "refresh failed" in down["age"] and down["cls"] == "stale"


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/needs_you.py:sync")
def test_the_alert_log_is_the_truth_not_the_state_file_beside_it(tmp_path):
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 60))
    path = needs_you.state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hold-benchmarks": {"source": "holds", "missed": 1}, "gone": {"source": "jobs", "missed": 1}}),
                    encoding="utf-8")
    r = gather(tmp_path)
    assert needs_you.sync(r, tmp_path)["began"] == ["hold-benchmarks"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"hold-benchmarks": {"source": "holds", "missed": 0}}
    path.write_text(json.dumps({"hold-benchmarks": {"source": "holds", "missed": 1}}), encoding="utf-8")
    monitor.record({"at": NOW, "kind": monitor.RECOVERED, "service": needs_you.SERVICE + "hold-benchmarks", "description": "x"}, tmp_path)
    assert needs_you.sync(r, tmp_path)["began"] == ["hold-benchmarks"]


def test_a_state_file_that_cannot_be_read_is_an_error_not_an_empty_memory(tmp_path):
    assert needs_you._load(tmp_path) == {}
    needs_you.state_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    needs_you.state_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not readable JSON"):
        needs_you._load(tmp_path)
    needs_you.state_path(tmp_path).write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="not the dict"):
        needs_you._load(tmp_path)


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/workqueue.py:retry:none-message")
def test_retry_says_which_of_no_such_job_and_not_failed_it_found(tmp_path):
    pending = plant_job(tmp_path, wq.PENDING, started=None, finished=None, note="", rc=None)
    with pytest.raises(ValueError, match="no job 9999"):
        wq.retry("9999")
    with pytest.raises(ValueError, match=f"job {pending} is pending; only a failed job can be retried"):
        wq.retry(pending)


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy", site="harness/commands/needs_you.py:cmd_needs_you:gather")
def test_the_command_from_a_scratch_home_sends_nothing_and_writes_only_its_own_home(tmp_path, monkeypatch, capsys):
    from harness import cli, features
    monkeypatch.setattr(features, "launchctl_list", lambda prefix, **kw: {})
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 60))
    assert not monitor.live_home(tmp_path)
    assert cli.main(["needs-you", "--alert"]) == 0
    got = [a for a in monitor.alerts(0, paths_home()) if a["kind"] == needs_you.KIND]
    assert any("Benchmarks held" in a["description"] for a in got)
    assert all(a["desktop"].startswith("not sent") and a["webhook"] in ("no webhook set",) or a["webhook"].startswith("not sent") for a in got)
    assert "Benchmarks held" in capsys.readouterr().out


def paths_home():
    from harness import paths
    return paths.home()
