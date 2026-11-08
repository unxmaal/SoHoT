"""One owner hold with scopes: benchmarks holds measurement, gpu holds batch GPU jobs and deploys; one release never lifts the other; the watchdog does not pause an eval for a client it already yielded to. #1558, #1508, #1564, #1509."""
import json
import sys
import time

import pytest

from harness import cli, contention, hold, paths, pressure
from harness import memory_store as ms
from harness import watchdog as wd
from harness import workqueue as wq
from tests.test_watchdog import Fake, Hand, P, run

SAID = "owner: the #1558 rebuild"


@pytest.fixture
def calm(monkeypatch):
    monkeypatch.setattr(wq, "_contended", wq._contended.real)
    monkeypatch.setattr(pressure, "sample", lambda: pressure.Pressure(level=pressure.NORMAL))


def test_each_scope_holds_its_own_jobs(calm):
    conn = ms.connect()
    gpu = wq.add([sys.executable, "-c", "pass"], title="render", conn=conn)
    ev = wq.add([sys.executable, "-c", "pass", "-m", "evals.run"], title="eval", conn=conn)
    hold.hold(conn, SAID)
    assert contention.verdict(conn)["open"], "a benchmark hold leaves the contention gate open"
    assert [j["id"] for j in wq.ready(conn)] == [gpu["id"]], "a benchmark hold keeps only the measurement job"
    hold.hold(conn, "owner: a video render", scope=hold.GPU)
    assert not contention.verdict(conn)["open"]
    assert wq._startable({}, time.time()) is None, "a gpu hold starts no batch GPU job"
    hold.release(conn, scope=hold.GPU)
    assert hold.active(conn) is not None and hold.active(conn, scope=hold.GPU) is None
    assert wq._startable({}, time.time())[0]["id"] == gpu["id"]
    assert ev["id"] not in [j["id"] for j in wq.ready(conn)]


def test_a_bare_release_is_refused_while_both_scopes_are_held(capsys):
    conn = ms.connect()
    assert cli.main(["hold", "benchmarks", SAID]) == 0
    assert cli.main(["hold", "gpu", "owner: a render"]) == 0
    capsys.readouterr()
    assert cli.main(["hold", "status"]) == 0
    out = capsys.readouterr().out
    assert "benchmarks held since" in out and "gpu held since" in out
    assert cli.main(["hold", "release"]) != 0
    assert "say which" in capsys.readouterr().err
    assert [h["kind"] for h in hold.actives(conn)] == [hold.BENCHMARKS, hold.GPU], "the refused release lifted nothing"
    assert cli.main(["hold", "release", "gpu"]) == 0
    assert [h["kind"] for h in hold.actives(conn)] == [hold.BENCHMARKS]
    assert cli.main(["hold", "release"]) == 0, "with one scope held, the scope may be left out"
    assert hold.actives(conn) == []


def test_an_unknown_scope_is_refused():
    conn = ms.connect()
    with pytest.raises(ValueError, match="scope"):
        hold.hold(conn, SAID, scope="night")
    assert cli.main(["hold", "release", "night"]) != 0


def test_a_hold_file_left_by_soh_gate_hold_still_holds_gpu_work_until_released():
    conn = ms.connect()
    (paths.home() / "queue").mkdir(parents=True, exist_ok=True)
    (paths.home() / "queue" / "hold").write_text(json.dumps({"said": "owner: old hold", "at": time.time() - 5,
                                                              "until": None}), encoding="utf-8")
    got = hold.active(conn, scope=hold.GPU)
    assert got["said"] == "owner: old hold" and hold.active(conn) is None
    assert not contention.verdict(conn)["open"]
    assert hold.release(conn, scope=hold.GPU)["said"] == "owner: old hold"
    assert hold.active(conn, scope=hold.GPU) is None and not (paths.home() / "queue" / "hold").exists()


def test_soh_gate_hold_names_the_hold_that_replaced_it(capsys):
    assert cli.main(["gate", "hold", "owner: x"]) != 0
    assert "soh hold gpu" in capsys.readouterr().err
    assert hold.actives(ms.connect()) == []


def _pause_findings(tmp_path, spans, request_at, now):
    """The contention findings for a job whose eval yielded over `spans`, with one client request ending at request_at."""
    conn = ms.connect()
    conn.execute("INSERT INTO gateway_requests (at, alias, purpose, total_s) VALUES (?, 'sohot-code', 'work', 1.0)",
                 (request_at - 1.0,))
    conn.commit()
    progress = run(4243, now=now, tmp=tmp_path)
    progress["serving_yields"] = {"count": len(spans), "seconds": 0.0, "spans": spans, "yielding_since": None}
    fake = Fake(tmp_path, procs=[P(4242, 1, 4242, 600, "uv run soh adopt --lane code"),
                                 P(4243, 4242, 4243, 600, "uv run python -m evals.run --modality code")],
                jobs={"0001": 4242}, lock={"kind": "eval", "pid": 4243, "pgid": 4243}, progress=[progress],
                rows={"0001": {"state": "running", "title": "adopt", "requested_by": ""}})
    world = wd.observe(fake, conn, now)
    found, _ = wd.judge(world)
    conn.close()
    return [f for f in found if f.criterion == contention.CRITERION]


def test_a_client_the_eval_already_yielded_to_does_not_pause_it(tmp_path):
    now = time.time()
    assert _pause_findings(tmp_path, [[now - 300, now - 100]], now - 200, now) == []


def test_a_client_served_outside_any_yield_still_pauses_it(tmp_path):
    now = time.time()
    found = _pause_findings(tmp_path, [[now - 300, now - 250]], now - 200, now)
    assert len(found) == 1 and found[0].evidence["served"] == 1


def test_a_yield_still_in_progress_covers_the_client_it_serves(tmp_path):
    now = time.time()
    progress = {"serving_yields": {"spans": [], "yielding_since": now - 30}}
    from harness import serve_lease
    assert serve_lease.during_yield(progress, now - 10, now)
    assert not serve_lease.during_yield(progress, now - 40, now)


def test_a_finished_yield_is_kept_as_a_span_in_the_runs_progress(monkeypatch):
    from evals import watch
    from harness import serve_lease
    w = watch.Watch(yielder=type("Y", (), {"yielding": lambda s, who: None, "between": lambda s: None})())
    held = iter(["a decide delegation", "a decide delegation", ""])
    monkeypatch.setattr(serve_lease, "held", lambda: next(held))
    monkeypatch.setattr(watch, "sleep", lambda s: None)
    assert w._serve()
    spans = w.served()["spans"]
    assert len(spans) == 1 and spans[0][0] <= spans[0][1]


def test_morning_names_both_holds():
    from harness import morning
    conn = ms.connect()
    hold.hold(conn, SAID)
    hold.hold(conn, "owner: a render", scope=hold.GPU)
    from harness.commands import morning as morning_cmd
    r = {"since": time.time() - 3600, "sweep": {"loop": None, "screened": {}, "measured": {"runs": [], "verdicts": {}},
                                                "paused": [], "stopped": [], "settled": {"verdicts": {}, "adopted": []}},
         "watchdog": [], "ci": {"available": False, "why": "-"}, "ledger": None, "stale": [],
         "deploy": {"available": False, "why": "-"}, "hold": hold.held(conn), "gpu_hold": hold.held(conn, scope=hold.GPU)}
    lines = morning.needs(r)
    assert [x for x in morning_cmd.render(r) if x.startswith("held ")] == [f"held      {r['hold']}",
                                                                          f"held      {r['gpu_hold']}"]
    assert morning.gather(conn, time.time(), time.time() - 3600)["gpu_hold"] == r["gpu_hold"]
    assert any(x.startswith("gpu held since") and "soh hold release gpu" in x for x in lines)
    assert any(x.startswith("benchmarks held since") and "soh hold release benchmarks" in x for x in lines)
