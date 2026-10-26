"""`soh canary`: each plant in its own isolated home, its verdict read back, nothing in the live store. #919."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import canary, cli, exclusive, heartbeat, morning, paths
from harness import memory_store as ms
from harness.commands import morning as morning_cmd

#: A child that writes what the plant's script says into whatever store its own environment names.
CHILD = """
import json, os, sys
from harness import memory_store as ms
plan = json.loads(os.environ["CANARY_TEST_PLAN"])
if os.environ.get("LH_GPU_LOCK_HELD") != "1":
    sys.exit("the child was not told the parent holds the GPU lock")
argv = sys.argv[1:]
if argv[:2] != ["canary", "spend"] and argv[:2] != ["discover", "--screen"]:
    sys.exit(0)
home = plan.get("write_to") or os.environ["LOCALHARNESS_HOME"]
conn = ms.connect(os.path.join(home, "discovery.db"))
ms.record(conn, ms.Seen(name=plan["name"], source="t", lane=plan["lane"]))
ms.decide(conn, plan["name"], plan["outcome"], tier=plan["tier"], detail=plan.get("detail", "t"),
          reason=plan["reason"], failure_class=plan.get("failure_class", ""))
conn.commit()
"""


@pytest.fixture
def child(tmp_path, monkeypatch):
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    seen = []

    def run(argv, env=None, **kw):
        seen.append((argv, env, exclusive.holder().get("kind")))
        return subprocess.run([sys.executable, str(script), *argv[3:]], env=env,
                              cwd=str(paths.REPO), capture_output=True, text=True)

    def plan(**kw):
        monkeypatch.setenv("CANARY_TEST_PLAN", json.dumps(kw))
    run.seen = seen
    return type("Child", (), {"run": staticmethod(run), "plan": staticmethod(plan)})


WORSE = canary.Plant("worse", "stt", "org/worse", ("declined", "adopt", "candidate"))
SCREEN = canary.Plant("load", "code", "org/load", ("screened", "screen", ""), through="screen")


def live_verdicts():
    conn = ms.connect()
    try:
        return conn.execute("SELECT count(*) FROM verdicts").fetchone()[0]
    finally:
        conn.close()


def test_every_shipped_plant_is_safe_to_run_isolated():
    assert [p.name for p in canary.PLANTS if canary.unsafe(p)] == []
    assert canary.unsafe(canary.Plant("x", "code", "org/x", ("measured", "adopt", "")))


def test_a_plant_reaching_its_verdict_in_its_own_home_is_ok_and_nothing_leaks(child, _home):
    child.plan(name="org/worse", lane="stt", outcome="declined", tier="adopt", reason="candidate")
    ms.connect().close()
    r = canary.run([WORSE], run=child.run)
    assert r["ok"] and r["leaked"] == 0, r
    p = r["plants"][0]
    assert p["observed"]["outcome"] == "declined" and p["observed"]["id"], p
    homes = {env[paths.ENV_VAR] for _, env, _ in child.run.seen}
    assert homes == {p["home"]} and Path(p["home"]).resolve() != Path(_home).resolve()
    # The live home's GPU lock is held for every child, which is told so and takes no lock of its own.
    assert {held for _, _, held in child.run.seen} == {"eval"}
    assert all(env[exclusive.HELD_ENV] == "1" for _, env, _ in child.run.seen)
    assert live_verdicts() == 0
    assert json.loads(Path(r["path"]).read_text(encoding="utf-8"))["plants"][0]["ok"]
    assert Path(r["path"]).parent == Path(_home) / "canary"


def test_a_plant_missing_its_verdict_is_a_miss(child):
    child.plan(name="org/worse", lane="stt", outcome="broken", tier="screen", reason="candidate")
    r = canary.run([WORSE], run=child.run)
    assert not r["ok"] and not r["plants"][0]["ok"]


def test_a_child_that_writes_the_live_store_is_caught(child, _home):
    ms.connect().close()
    child.plan(name="org/worse", lane="stt", outcome="declined", tier="adopt", reason="candidate",
               write_to=str(_home))
    r = canary.run([WORSE], run=child.run)
    assert r["leaked"] == 1 and not r["ok"], r


def test_a_screen_plant_never_reaches_the_spend(child):
    child.plan(name="org/load", lane="code", outcome="screened", tier="screen", reason="")
    r = canary.run([SCREEN], run=child.run)
    assert r["ok"], r
    asked = [argv[3:5] for argv, _, _ in child.run.seen]
    assert ["canary", "spend"] not in asked and ["discover", "--screen"] in asked


def test_the_live_home_is_refused(_home):
    with pytest.raises(RuntimeError):
        canary.run_plant(WORSE, Path(_home), run=lambda *a, **k: pytest.fail("ran in the live home"))


def test_spend_refuses_the_live_home(monkeypatch, _home):
    monkeypatch.setattr(paths, "DEFAULT_HOME", Path(_home))
    assert cli.main(["canary", "spend", "--lane", "stt"]) == 1


def test_the_known_better_incumbent_is_adopted_by_hand_in_the_isolated_store(tmp_path):
    plant = next(p for p in canary.PLANTS if p.name == "stt-known-better")
    conn = ms.connect(tmp_path / "discovery.db")
    try:
        canary.seed(conn, plant)
        got = canary.observe(conn, plant)
    finally:
        conn.close()
    assert "v3" in got["serves"] and got["outcome"] == "", got


@pytest.mark.gauntlet("one-default-tuned-for-one-member-applied-to-all", site="harness/canary.py:run(wait_h)")
def test_a_running_loop_is_waited_for_then_given_up_on(monkeypatch, child):
    monkeypatch.setattr(heartbeat, "summary", lambda alive=None: {"status": "running"})
    clock = iter(range(0, 10 ** 6, 1000))
    r = canary.run([WORSE], run=child.run, now=lambda: float(next(clock)), sleep=lambda s: None, wait_h=1)
    assert r["skipped"] and not r["ok"] and child.run.seen == []
    assert "did not run" in canary.morning_line(r["started"])


def _receipt(started, ok=True, leaked=0):
    return canary.write({"started": started, "finished": started, "leaked": leaked, "ok": ok,
                         "plants": [{"plant": "stt-known-worse", "ok": ok}]})


def test_morning_names_a_miss_a_leak_and_a_stale_canary(monkeypatch):
    now = time.time()
    assert "no receipt newer than 8 days" in canary.morning_line(now)
    _receipt(now - 9 * 86400)
    assert "no receipt newer than 8 days" in canary.morning_line(now)
    _receipt(now - 3600)
    assert canary.morning_line(now) == ""
    _receipt(now - 60, ok=False)
    assert "stt-known-worse" in canary.morning_line(now)
    _receipt(now - 30, leaked=2)
    assert "leaked 2" in canary.morning_line(now)


def test_soh_morning_prints_the_canary_line(monkeypatch, capsys):
    monkeypatch.setattr(morning, "lane_health", lambda lane: {"lane": lane, "generating": None, "why": "t"})
    monkeypatch.setattr(morning, "_gh", lambda argv: "[]")
    monkeypatch.setattr(morning, "_git", lambda argv: "")
    ms.connect().close()
    _receipt(time.time() - 60, ok=False)
    assert cli.main(["morning", "--no-model"]) == 0
    out = capsys.readouterr().out
    assert "canary    the canary's plants missed their expected verdicts: stt-known-worse" in out
    assert "needs a person:" in out


def _stored_pair(conn, lane, better, worse, n=40, path="r1"):
    from harness import candidates
    conn.execute("INSERT INTO runs (path, lane, tier, generated_at, recorded_at) VALUES (?, ?, ?, ?, 0)",
                 (path, lane, "screen" if path == "screen" else "measure", {"old": 2, "new": 1, "screen": 3}.get(path, 0)))
    rid = conn.execute("SELECT id FROM runs WHERE path = ?", (path,)).fetchone()[0]
    for spec, errs in ((better, lambda i: 0), (worse, lambda i: 1 if i % 2 else 0)):
        cid = candidates.ensure(conn, spec, lane=lane)
        for i in range(n):
            conn.execute("INSERT INTO results (run_id, seq, candidate_id, candidate, case_id, passed, metrics) "
                         "VALUES (?,?,?,?,?,1,?)", (rid, i, cid, spec.split("/")[-1], f"c{i}",
                                                    json.dumps({"wer": errs(i) / 20, "wer_errors": errs(i),
                                                                "wer_words": 20})))
    conn.commit()


def test_check_says_whether_the_stored_results_separate_each_pair(tmp_path):
    from harness import screen
    conn = ms.connect(tmp_path / "s.db")
    try:
        v2, v3 = (screen.candidate_for("stt", f"mlx-community/parakeet-tdt-{v}") for v in ("1.1b", "0.6b-v3"))
        _stored_pair(conn, "stt", v2, v3)
        got = {p.name: canary.separable(conn, p) for p in canary.PLANTS}
    finally:
        conn.close()
    assert got["stt-known-worse"]["ok"] and got["stt-known-better"]["ok"], got
    assert got["gguf-first"]["ok"]


def test_check_misses_a_pair_the_gate_cannot_separate(tmp_path):
    from harness import screen
    conn = ms.connect(tmp_path / "s.db")
    try:
        v2, v3 = (screen.candidate_for("stt", f"mlx-community/parakeet-tdt-{v}") for v in ("1.1b", "0.6b-v3"))
        _stored_pair(conn, "stt", v3, v2)
        got = canary.separable(conn, next(p for p in canary.PLANTS if p.name == "stt-known-worse"))
    finally:
        conn.close()
    assert not got["ok"], got


def test_the_weekly_unit_runs_the_canary_on_the_scheduler_only():
    root = Path(paths.REPO)
    gen = (root / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    import re
    for name in ("SERVICES", "PERIODIC", "SCHEDULER_ONLY"):
        line = re.search(rf"^(?:declare -a )?{name}=[(\"]([^)\"]*)", gen, re.M).group(1).split()
        assert "canary" in line, name
    body = (root / "scripts" / "serve-canary.sh").read_text(encoding="utf-8")
    assert "soh canary --run" in body


def test_dry_run_lists_every_plant(capsys):
    assert cli.main(["canary"]) == 0
    out = capsys.readouterr().out
    assert all(p.name in out for p in canary.PLANTS) and "canary spend" in out


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/canary.py:separable")
def test_check_reads_the_newest_run_holding_both(tmp_path):
    from harness import screen
    conn = ms.connect(tmp_path / "s.db")
    try:
        v2, v3 = (screen.candidate_for("stt", f"mlx-community/parakeet-tdt-{v}") for v in ("1.1b", "0.6b-v3"))
        # Inserted first, generated last: recency is the run's own time, not its row id.
        _stored_pair(conn, "stt", v2, v3, path="old")
        _stored_pair(conn, "stt", v3, v2, path="new")
        _stored_pair(conn, "stt", v3, v2, path="screen")
        got = canary.separable(conn, next(p for p in canary.PLANTS if p.name == "stt-known-worse"))
    finally:
        conn.close()
    assert got["ok"] and got["run_id"] == 1, got


LOADS = canary.Plant("loads", "code", "org/load", ("screened", "screen", ""), through="screen", requires="loads")


def _llamacpp(monkeypatch, build):
    monkeypatch.setattr(ms, "this_machine", lambda: {"versions": {"llama.cpp": build}})


def test_the_children_are_told_whose_router_log_their_screen_lands_in(child, _home):
    child.plan(name="org/load", lane="code", outcome="screened", tier="screen", reason="")
    canary.run([SCREEN], run=child.run)
    from harness import load_log
    assert {env[load_log.SERVING_ENV] for _, env, _ in child.run.seen} == {str(paths.home())}


def test_a_plant_whose_gguf_does_not_load_here_is_invalid_not_a_miss(child, monkeypatch):
    """#1006: Qwengram's nextn tensors fail on llama.cpp 11146, so the canary checked the plant, not the pipeline."""
    from harness import reasons
    _llamacpp(monkeypatch, "11146")
    child.plan(name="org/load", lane="code", outcome="declined", tier="screen", reason="runtime",
               failure_class=reasons.LOAD_FAILED_RUNTIME, detail="llama-server: wrong number of tensors")
    r = canary.run([LOADS], run=child.run)
    p = r["plants"][0]
    assert not r["ok"] and not p["ok"] and p["version"] == "11146"
    assert "the GGUF loads under this llama.cpp build" in p["invalid"] and "wrong number of tensors" in p["invalid"]
    assert "invalid" in canary.morning_line() and "missed" not in canary.morning_line()


def test_an_invalid_plant_is_not_planted_again_until_its_runtime_changes(child, monkeypatch):
    from harness import reasons
    _llamacpp(monkeypatch, "11146")
    child.plan(name="org/load", lane="code", outcome="declined", tier="screen", reason="runtime",
               failure_class=reasons.LOAD_FAILED_RUNTIME)
    canary.run([LOADS], run=child.run)
    planted = len(child.run.seen)
    again = canary.run([LOADS], run=child.run, now=lambda: time.time() + 60)
    assert len(child.run.seen) == planted and again["plants"][0]["invalid"] and not again["ok"]
    _llamacpp(monkeypatch, "11200")
    child.plan(name="org/load", lane="code", outcome="screened", tier="screen", reason="")
    upgraded = canary.run([LOADS], run=child.run, now=lambda: time.time() + 120)
    assert len(child.run.seen) > planted and upgraded["ok"], upgraded


def test_a_screen_the_harness_could_not_read_is_still_a_miss(child, monkeypatch):
    from harness import reasons
    _llamacpp(monkeypatch, "11146")
    child.plan(name="org/load", lane="code", outcome="queued", tier="screen", reason="harness",
               failure_class=reasons.LOAD_LOG_UNREAD)
    p = canary.run([LOADS], run=child.run)["plants"][0]
    assert not p["ok"] and not p["invalid"]


def test_run_json_prints_the_receipt_and_exits_nonzero_on_a_miss(child, monkeypatch, capsys):
    """#1006: emit(r["ok"], **r) raised TypeError after the report, so --json never printed."""
    child.plan(name="org/load", lane="code", outcome="broken", tier="screen", reason="candidate")
    monkeypatch.setattr(canary, "PLANTS", (SCREEN,))
    real = canary.run
    monkeypatch.setattr(canary, "run", lambda plants, wait_h, replays=(): real(plants, run=child.run, wait_h=wait_h))
    assert cli.main(["canary", "--run", "--plant", "load", "--json"]) == 1
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert got["ok"] is False and got["plants"][0]["plant"] == "load" and got["path"]


def test_every_shipped_precondition_is_known():
    assert all(p.requires in canary.PRECONDITIONS for p in canary.PLANTS if p.requires)
    assert canary.unsafe(canary.Plant("x", "code", "org/x", ("screened", "screen", ""), through="screen",
                                      requires="nonsense"))
