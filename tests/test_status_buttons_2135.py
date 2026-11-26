"""Per-item buttons on the status page: each listed job, unit, node, lane and the discovery loop, rendered, pressed, confirmed, and the
state read back from a scratch home. Only launchd is faked (the unit restart). #2135."""
from __future__ import annotations

import json
import re
import time

import pytest

from harness import features, hold, nodes, owner_actions as oa, status_buttons, status_page as sp
from harness import memory_store as ms
from harness import workqueue as wq

NOW = time.time()
HOST = {"host": "localhost:8899"}
NODES = """# the owner's nodes
nodes:
  - name: styx
    api_base: http://127.0.0.1:18082/v1
    engine: llama-server
    models: [m1]   # keep this comment
    machine: "m"
    parked: false
  - name: olm
    api_base: http://127.0.0.1:18083/v1
    engine: llama-server
    models: [m1]
    machine: "m"
    parked: true
"""
UNITS = [{"kind": "unit", "name": n, "state": s, "by": "x", "since": None}
         for n, s in (("gateway", "on"), ("mlx", "on demand"), ("discover", "off"))]
LANES = [{"kind": "lane", "name": n, "state": s, "by": "x", "since": None} for n, s in (("code", "on demand"), ("video", "parked"))]


def with_conn(fn):
    conn = ms.connect()
    try:
        return fn(conn)
    finally:
        conn.close()


def rows_features(conn, now, q):
    return {"rows": [*UNITS, *features.nodes_rows(nodes._all()), *LANES]}


def gather(tmp_path):
    (tmp_path / "checkout" / ".git").mkdir(parents=True, exist_ok=True)
    return sp.gather(NOW, connect=ms.connect, beat={"status": "finished", "started": NOW - 3600, "finished": NOW - 600, "rc": 0,
                                                    "line": "ok"}, where=tmp_path / "checkout", git=lambda argv: "",
                     mon=lambda: {"installed": True, "running": True, "current": True, "webhook": True, "problems": [],
                                  "summary": ["Service Name   Status   Type", "gateway   OK   Process"]},
                     features=rows_features, home=tmp_path,
                     health=lambda lane: {"lane": lane, "spec": "m", "base": "http://127.0.0.1:1", "generating": True, "why": ""},
                     reach=lambda since, now: [], flow=lambda now: {"available": False, "why": "none"})


def add_job(tmp_path, argv=("true",), title="job", **kw):
    return with_conn(lambda c: wq.add(list(argv), title=title, cwd=str(tmp_path), conn=c, **kw))["id"]


def set_state(job, state, **cols):
    sets = ", ".join(f"{k} = ?" for k in ("state", *cols))
    with_conn(lambda c: c.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (state, *cols.values(), int(job))) and c.commit())


@pytest.fixture
def home_nodes(tmp_path, monkeypatch):
    f = tmp_path / "nodes.yaml"
    f.write_text(NODES, encoding="utf-8")
    monkeypatch.setenv(nodes.ENV_VAR, str(f))
    return f


@pytest.fixture
def client(monkeypatch, tmp_path):
    srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")
    from starlette.testclient import TestClient
    monkeypatch.setattr(sp, "cached", lambda: gather(tmp_path))
    app = srv.SERVER.streamable_http_app(transport_security=srv.transport_security("0.0.0.0", 8899), host="0.0.0.0")
    return TestClient(app)


@pytest.fixture
def launchd(monkeypatch):
    """The one fake: scripts/launchd.sh restart is recorded instead of run; every other verb runs as its own soh process."""
    calls = []
    real = oa.run_verb

    def fake(argv, run=None):
        if argv[:1] != ["unit-restart"]:
            return real(argv, run)
        from harness import unit_restart

        def launchd_sh(cmd, **kw):
            calls.append([c.rsplit("/", 1)[-1] if i == 0 else c for i, c in enumerate(cmd)])
            return type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        got = unit_restart.restart(argv[1], run=launchd_sh, platform="darwin")
        return {"rc": got["rc"], "out": got["line"]}
    monkeypatch.setattr(oa, "run_verb", fake)
    return calls


def forms(html):
    return [dict(re.findall(r"name='(\w+)' value='([^']*)'", f)) for f in re.findall(r"<form.*?</form>", html, re.S)]


def mine(html, action, arg=""):
    return [f for f in forms(html) if f["action"] == action and f.get("arg", "") == arg]


def press(client, action, arg=""):
    """The two presses a button takes through POST /status/action, from the page as served."""
    page = client.get("/status", headers=HOST).text
    form = next(f for f in mine(page, action, arg))
    first = client.post("/status/action", data=form, headers=HOST)
    assert first.status_code == 200 and "Confirm" in first.text, first.text
    nonce = re.search(r"name='confirm' value='([^']+)'", first.text).group(1)
    done = client.post("/status/action", data={**form, "confirm": nonce}, headers=HOST)
    assert done.status_code == 200 and "Done" in done.text, done.text
    return done


def discovery_rows(page):
    return re.search(r"<div class='rows' data-rows='discovery'>.*?</div></div>", page, re.S).group(0)


def audit_lines(tmp_path):
    from harness import paths
    return [json.loads(x) for x in (paths.home() / oa.AUDIT).read_text(encoding="utf-8").splitlines()]


def row(page, attr, value):
    return re.search(rf"<div class='(?:jr|fr)'[^>]*{attr}='{re.escape(value)}'.*?</div>(?=<div|</div>)", page, re.S)


def test_each_listed_job_unit_node_and_lane_row_carries_its_buttons(tmp_path, client, home_nodes):
    held_job = add_job(tmp_path, ("soh", "reverify"), "reverify code")
    second = add_job(tmp_path, title="second")
    running, failed = add_job(tmp_path, title="runs"), add_job(tmp_path, title="broke")
    set_state(running, wq.RUNNING, started_at=NOW - 60)
    set_state(failed, wq.FAILED, finished_at=NOW - 60, rc=1, note="boom")
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 60))
    page = client.get("/status", headers=HOST).text
    acts = lambda html: sorted(f["action"] for f in forms(html))  # noqa: E731
    jr = lambda j: re.search(rf"<div class='jr' data-job='{j}'>.*?</div>", page, re.S).group(0)  # noqa: E731
    assert acts(jr(held_job)) == ["job_cancel", "job_let"]
    assert acts(jr(second)) == ["job_cancel", "job_first"]
    assert acts(jr(running)) == ["job_cancel"] and acts(jr(failed)) == ["job_retry"]
    fr = lambda n: re.search(rf"<div class='fr'[^>]*><span class='fs [a-z]*'>[^<]*</span><span class='fn'>{n}</span>.*?</div>", page, re.S).group(0)  # noqa: E731
    assert acts(fr("gateway")) == ["unit_restart"] and acts(fr("mlx")) == ["unit_restart"]
    assert acts(fr("discover")) == []
    assert acts(fr("styx")) == ["node_park"] and acts(fr("olm")) == ["node_unpark"]
    assert acts(fr("code")) == ["lane_reverify"] and acts(fr("video")) == []
    assert acts(discovery_rows(page)) == ["discovery_on"]


def test_a_device_that_may_not_press_sees_no_row_buttons(tmp_path, home_nodes):
    add_job(tmp_path)
    page = sp.page(gather(tmp_path), now=NOW)
    assert "class='act'" not in page and "data-rows" not in page


def test_a_waiting_job_is_cancelled_from_its_row(tmp_path, client):
    job = add_job(tmp_path, title="not wanted")
    press(client, "job_cancel", job)
    assert wq.get(job)["state"] == wq.CANCELLED
    assert audit_lines(tmp_path)[-1]["outcome"] == "rc 0" and audit_lines(tmp_path)[-1]["arg"] == job


def test_a_running_job_row_presses_jobs_cancel_with_its_id(tmp_path, client):
    """The process boundary is faked: a planted running job has no process of its own to stop."""
    job = add_job(tmp_path, title="runs")
    set_state(job, wq.RUNNING, started_at=NOW - 60)
    form = mine(client.get("/status", headers=HOST).text, "job_cancel", job)[0]
    ran = []
    fake = lambda cmd, **kw: ran.append(cmd[3:]) or type("P", (), {"returncode": 0, "stdout": "cancelled", "stderr": ""})()  # noqa: E731
    who = {"name": "p", "id": "p"}
    r = gather(tmp_path)
    asked = oa.press("p", {}, {**form, "token": oa.token("p", who, NOW)}, r, now=NOW, home=tmp_path, run=fake)
    nonce = re.search(r"name='confirm' value='([^']+)'", asked[1]).group(1)
    assert oa.press("p", {}, {**form, "token": oa.token("p", who, NOW), "confirm": nonce}, r, now=NOW, home=tmp_path, run=fake)[0] == 200
    assert ran == [["jobs", "cancel", job]]


def test_a_failed_job_is_retried_from_the_queue_row(tmp_path, client):
    job = add_job(tmp_path, title="broke")
    set_state(job, wq.FAILED, finished_at=NOW - 60, rc=1, note="boom")
    press(client, "job_retry", job)
    assert [j["state"] for j in wq.jobs() if j["title"] == "broke"].count(wq.PENDING) == 1


def test_a_held_job_is_let_through_the_hold(tmp_path, client):
    job = add_job(tmp_path, ("soh", "reverify"), "reverify code")
    with_conn(lambda c: hold.hold(c, "owner: busy", now=NOW - 60))
    assert with_conn(lambda c: hold.held_back(c, wq.get(job, conn=c), hold.active(c)))
    press(client, "job_let", job)
    assert not with_conn(lambda c: hold.held_back(c, wq.get(job, conn=c), hold.active(c)))
    assert not mine(client.get("/status", headers=HOST).text, "job_let", job)


def test_a_waiting_job_is_raised_above_the_others(tmp_path, client):
    first, last = add_job(tmp_path, title="first"), add_job(tmp_path, title="last")
    assert [j["id"] for j in wq.pending()] == [first, last]
    press(client, "job_first", f"{last}:1")
    assert [j["id"] for j in wq.pending()] == [last, first] and wq.get(last)["priority"] == 1


def test_a_node_is_parked_and_unparked_in_the_nodes_file_keeping_its_comments(tmp_path, client, home_nodes):
    press(client, "node_park", "styx")
    assert nodes.parked_names() == ["styx", "olm"] and "# keep this comment" in home_nodes.read_text(encoding="utf-8") and "# the owner's nodes" in home_nodes.read_text(encoding="utf-8")
    press(client, "node_unpark", "olm")
    assert nodes.parked_names() == ["styx"]
    assert [x["action"] + ":" + x["arg"] for x in audit_lines(tmp_path) if x["press"] == "confirm"] == ["node_park:styx", "node_unpark:olm"]


def test_a_unit_is_restarted_through_launchd_sh_only(tmp_path, client, launchd):
    press(client, "unit_restart", "mlx")
    assert launchd == [["launchd.sh", "restart", "mlx"]]


def test_a_lane_reverify_runs_the_lanes_verb(tmp_path, client):
    press(client, "lane_reverify", "code")
    assert audit_lines(tmp_path)[-1]["outcome"] == "rc 0"


def test_discovery_starts_from_its_row_and_stops_from_the_waiting_step(tmp_path, client):
    from harness.commands import loop_steps
    assert [f["action"] for f in forms(discovery_rows(client.get("/status", headers=HOST).text))] == ["discovery_on"]
    press(client, "discovery_on")
    waiting = with_conn(loop_steps.waiting)
    assert len(waiting) == 1
    shown = forms(discovery_rows(client.get("/status", headers=HOST).text))
    assert [(f["action"], f["arg"]) for f in shown] == [("discovery_off", str(waiting[0]["id"]))]
    press(client, "discovery_off", str(waiting[0]["id"]))
    assert with_conn(loop_steps.waiting) == []


def test_a_forged_choice_is_refused_and_nothing_runs(tmp_path, client, home_nodes, launchd):
    job = add_job(tmp_path)
    r = gather(tmp_path)
    forged = [("job_cancel", "0042"), ("job_let", job), ("job_first", f"{job}:5"), ("job_first", "0042:5"), ("unit_restart", "launchd"),
              ("unit_restart", "discover"), ("node_park", "ghost"), ("node_park", "olm"), ("node_unpark", "styx"),
              ("lane_reverify", "video"), ("lane_reverify", "--dry-run"), ("job_retry", job)]
    who = {"name": "p", "id": "p"}
    for action, arg in forged:
        code, text = oa.press("p", {}, {"token": oa.token("p", who, NOW), "action": action, "arg": arg}, r, now=NOW, home=tmp_path,
                              run=lambda *a, **k: pytest.fail(f"a forged {action} {arg} ran"))
        assert code == 400 and "does not offer" in text, (action, arg)
    assert wq.get(job)["state"] == wq.PENDING and nodes.parked_names() == ["olm"] and launchd == []


def test_a_forwarded_press_and_a_replayed_confirmation_do_nothing(tmp_path, client):
    form = mine(client.get("/status", headers=HOST).text, "lane_reverify", "code")[0]
    assert client.post("/status/action", data=form, headers={**HOST, "x-forwarded-for": "1.2.3.4"}).status_code == 403
    first = client.post("/status/action", data=form, headers=HOST)
    nonce = re.search(r"name='confirm' value='([^']+)'", first.text).group(1)
    assert client.post("/status/action", data={**form, "confirm": nonce}, headers=HOST).status_code == 200
    assert client.post("/status/action", data={**form, "confirm": nonce}, headers=HOST).status_code == 409
    assert len([x for x in audit_lines(tmp_path) if x["outcome"] == "rc 0"]) == 1


def test_the_queue_section_lists_at_most_its_cap_of_waiting_jobs_in_run_order(tmp_path):
    ids = [add_job(tmp_path, title=f"j{i}") for i in range(sp.WAITING_SHOWN + 3)]
    got = gather(tmp_path)["queue"]
    assert got["pending"] == len(ids) and [j["id"] for j in got["waiting"]] == ids[:sp.WAITING_SHOWN]


def test_node_park_edits_only_its_line_and_refuses_what_it_cannot_set(tmp_path):
    from harness import node_park
    f = tmp_path / "n.yaml"
    f.write_text(NODES.replace("    parked: false\n", ""), encoding="utf-8")
    assert node_park.set_parked("styx", True, f)["changed"] and "    parked: true\n" in f.read_text(encoding="utf-8")
    assert f.read_text(encoding="utf-8").count("parked:") == 2 and f.read_text(encoding="utf-8").startswith("# the owner's nodes\nnodes:\n  - name: styx")
    before = f.read_text(encoding="utf-8")
    assert node_park.set_parked("styx", True, f)["changed"] is False
    with pytest.raises(ValueError, match="not one"):
        node_park.set_parked("ghost", True, f)
    with pytest.raises(ValueError, match="no nodes file"):
        node_park.set_parked("styx", True, tmp_path / "none.yaml")
    assert f.read_text(encoding="utf-8") == before
