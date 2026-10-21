"""Memory at warn with no swapping gives back idle models and never pauses; a memory pause leaves the sweep going on what fits (#1082)."""
import io
import json
from pathlib import Path

from evals import watch
from harness import ceiling, mlx_server, morning, router
from harness import memory_store as ms
from harness import watchdog as wd
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from harness.commands import morning as morning_cmd
from tests.test_resume_813 import Eval, _measure, _rows, _sweep, world  # noqa: F401
from tests.test_watchdog import NIGHT, Fake, P, Pressure

DISCOVER = "/bin/bash scripts/serve-discover.sh discover --loop"
SCREEN = "/usr/bin/python3 -m evals.run --modality code --candidates llamacpp:Qwopus"
EDGE0 = "Edge0/Edge0-35B-A3B-preview"


class Night(Fake):
    """The 2026-10-20 night: the discover loop screens a GGUF while the mlx server still holds the last screen's model."""

    def __init__(self, tmp_path, pressure, held=EDGE0, protected=(), specs=None, **kw):
        progress = {"state": "running", "pid": 237, "done": 2, "total": 5, "started_at": NIGHT - 600,
                    "last_progress_at": NIGHT - 30, "_dir": str(tmp_path), "pause_file": str(tmp_path / "pause"),
                    "specs": specs if specs is not None else {"q": "llamacpp:Qwopus3.6-27B,temperature=0"}}
        super().__init__(tmp_path, procs=[P(236, 1, 236, 4000, DISCOVER), P(237, 236, 237, 600, SCREEN)],
                         discover=236, progress=[progress], pressure=pressure, **kw)
        self._held, self._protected = held, set(protected)

    def mlx_held(self):
        return self._held

    def protected(self):
        return self._protected


class Ladder(wd.Hands):
    def __init__(self):
        super().__init__(run=None, environ={})
        self.done = []

    def do(self, action, f):
        self.done.append((f.criterion, action))
        return "ok"


def _wakes(tmp_path, pressures, **kw):
    conn, hand = ms.connect(), Ladder()
    try:
        for i, p in enumerate(pressures):
            wd.wake(conn, Night(tmp_path, p, **kw), hand, act=True, now=NIGHT + i * 300, say=lambda *_: None)
        rows = [dict(r) for r in conn.execute("SELECT criterion, action, evidence FROM watchdog_actions ORDER BY id")]
    finally:
        conn.close()
    return hand.done, rows


def test_warn_with_no_swapping_notifies_then_unloads_and_never_pauses(tmp_path):
    done, rows = _wakes(tmp_path, [Pressure(level=2, alarming=True, swapouts=0)] * 5)
    assert done == [("memory_warn", wd.NOTIFY)] * 2 + [("memory_warn", wd.UNLOAD)] * 3
    assert all(r["action"] != wd.PAUSE for r in rows)
    ev = json.loads(rows[-1]["evidence"])
    assert ev["pressure_level"] == 2 and ev["swapouts_per_min"] == 0
    assert ev["idle"] == [{"server": "mlx", "model": EDGE0}]


def test_warn_with_an_unknown_swap_rate_is_not_read_as_swapping(tmp_path):
    done, _ = _wakes(tmp_path, [Pressure(level=2, alarming=True, swapouts=None)] * 3)
    assert [a for _, a in done] == [wd.NOTIFY, wd.NOTIFY, wd.UNLOAD]


def test_swapouts_over_the_limit_still_pause(tmp_path):
    step = int(wd.SWAPOUT_MAX_PER_MIN * 5) * 2
    done, _ = _wakes(tmp_path, [Pressure(level=2, alarming=True, swapouts=1000 + i * step) for i in range(4)])
    # The first wake has no earlier counter to rate against: warn alone.
    assert done == [("memory_warn", wd.NOTIFY), ("memory", wd.NOTIFY), ("memory", wd.NOTIFY), ("memory", wd.PAUSE)]


def test_critical_pressure_pauses_with_no_swapping(tmp_path):
    done, _ = _wakes(tmp_path, [Pressure(level=4, alarming=True, swapouts=0)] * 3)
    assert done == [("memory", wd.NOTIFY), ("memory", wd.NOTIFY), ("memory", wd.PAUSE)]


def _idle(tmp_path, **kw):
    world = wd.observe(Night(tmp_path, Pressure(level=2, alarming=True), **kw), None, NIGHT)
    return wd.idle(world)


def test_a_model_a_running_eval_uses_or_a_lane_serves_is_never_idle(tmp_path):
    assert _idle(tmp_path) == [{"server": "mlx", "model": EDGE0}]
    assert _idle(tmp_path, protected=[EDGE0]) == []
    assert _idle(tmp_path, specs={"e": f"{EDGE0},temperature=0"}) == []
    assert _idle(tmp_path, held=None) == []
    assert _idle(tmp_path, resident=["Qwopus3.6-27B", "Stale-4B"]) == [
        {"server": "router", "model": "Stale-4B"}, {"server": "mlx", "model": EDGE0}]


def test_an_eval_with_no_progress_file_makes_nothing_idle(tmp_path):
    fake = Night(tmp_path, Pressure(level=2, alarming=True), resident=["Stale-4B"])
    fake.runs = []
    assert wd.idle(wd.observe(fake, None, NIGHT)) == []


def test_unload_on_warn_releases_each_idle_model_past_the_eval_lock(monkeypatch):
    asked = []
    monkeypatch.setattr(mlx_server, "release", lambda model, why, **kw: asked.append(("mlx", model)) or True)
    monkeypatch.setattr(router, "release",
                        lambda stems, why, **kw: asked.append(("router", stems, kw.get("proven_idle"))) or [])
    f = wd.Finding("memory_warn", wd.Subject("discover", "discover pid 236", "t"),
                   {"idle": [{"server": "router", "model": "Stale-4B"}, {"server": "mlx", "model": EDGE0}]})
    out = wd.Hands().do(wd.UNLOAD, f)
    assert asked == [("router", ["Stale-4B"], True), ("mlx", EDGE0)]
    assert out == f"kept router Stale-4B; unloaded mlx {EDGE0}"
    nothing = wd.Finding("memory_warn", f.subject, {"idle": []})
    assert wd.Hands().do(wd.UNLOAD, nothing).startswith("nothing idle to unload")


class MlxStub:
    """mlx_lm.server's /sohot/loaded and its hot swap: a request naming no model loads the boot model."""

    def __init__(self, holds, boot="mlx-community/Qwen2.5-1.5B-Instruct-4bit"):
        self.holds, self.boot, self.posts = holds, boot, []

    def __call__(self, req, timeout):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith(mlx_server.LOADED_PATH):
            return io.BytesIO(json.dumps({"model": self.holds}).encode())
        body = json.loads(req.data)
        self.posts.append(body)
        self.holds = body.get("model") or self.boot
        return io.BytesIO(b'{"choices": []}')


def test_release_swaps_the_mlx_server_back_to_its_boot_model():
    stub, said = MlxStub(EDGE0), []
    assert mlx_server.release(EDGE0, "test", base="http://mlx.test", keep=set(), opener=stub, say=said.append)
    assert stub.holds == stub.boot and stub.posts == [{"messages": [{"role": "user", "content": "ok"}], "max_tokens": 1}]
    assert said == [f"  mlx: unloaded {EDGE0} (test)"]


def test_release_keeps_a_protected_model_another_one_and_the_boot_model():
    stub = MlxStub(EDGE0)
    assert not mlx_server.release(EDGE0, "t", base="http://mlx.test", keep={EDGE0}, opener=stub, say=lambda *_: None)
    assert not mlx_server.release("other/model", "t", base="http://mlx.test", keep=set(), opener=stub,
                                  say=lambda *_: None)
    assert stub.posts == [] and stub.holds == EDGE0
    boot = MlxStub("mlx-community/Qwen2.5-1.5B-Instruct-4bit")
    said = []
    assert not mlx_server.release(boot.holds, "t", base="http://mlx.test", keep=set(), opener=boot, say=said.append)
    assert "boot model" in said[0]


def test_release_spec_matches_the_spec_s_model_through_a_method_and_options():
    stub = MlxStub(EDGE0)
    assert not mlx_server.release_spec("llamacpp:Qwopus", "t", base="http://mlx.test", keep=set(), opener=stub,
                                       say=lambda *_: None)
    assert mlx_server.release_spec(f"best-of:3:{EDGE0},temperature=0", "t", base="http://mlx.test", keep=set(),
                                   opener=stub, say=lambda *_: None)


def test_a_watchdog_pause_names_its_criterion_in_the_pause_file(tmp_path):
    run = {"_dir": str(tmp_path), "pause_file": str(tmp_path / watch.PAUSE_FILE)}
    f = wd.Finding("memory", wd.Subject("eval", "eval pgid 1", "t", progress=run), {})
    assert "pause file written" in wd.Hands().do(wd.PAUSE, f)
    assert watch.pause_reason(tmp_path) == "memory"
    (tmp_path / watch.PAUSE_FILE).write_text("", encoding="utf-8")
    assert watch.pause_reason(tmp_path) == ""
    assert watch.pause_reason(tmp_path / "nowhere") == ""


# --- the measure step after a pause ---------------------------------------------

def _paused_by(monkeypatch, reason):
    fake = Eval(rows=_rows(5))

    def requested(argv, **kw):
        got = fake(argv, **kw)
        out = Path(argv[argv.index("--out") + 1])
        p = json.loads((out / watch.PROGRESS).read_text(encoding="utf-8"))
        (out / watch.PROGRESS).write_text(json.dumps({**p, "why": "paused on request, 3 case(s) left"}),
                                          encoding="utf-8")
        watch.ask_pause(out, reason)
        return got
    monkeypatch.setattr(measure_cmd, "_launch", requested)
    sweep = _sweep()
    _measure(sweep)
    return sweep


def test_a_memory_pause_squeezes_the_sweep_and_any_other_request_halts_it(monkeypatch, world):
    squeezed = _paused_by(monkeypatch, "memory")
    assert squeezed.squeezed.startswith("paused at 10/") and squeezed.halted == ""
    halted = _paused_by(monkeypatch, "daytime_gpu")
    assert halted.halted.startswith("paused at") and halted.squeezed == ""


def _run_loop(monkeypatch, first_pause, room):
    ran = []

    def measure(a, row, sweep=None):
        ran.append(row["name"])
        if len(ran) == 1:
            setattr(sweep, first_pause, f"paused at 1/2 ({row['name']})")
        return 0
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", measure)
    monkeypatch.setattr(loop_cmd, "_beat", lambda *a, **k: None)
    sweep = _sweep()
    rows = [{"name": n, "lane": "svg"} for n in ("deepen:big", "huge", "trace:mflux:dev", "best-of:3:q3-30b")]
    loop_cmd._measure_all(None, rows, sweep, [], room=room)
    return ran, sweep


NEEDS = {"huge": (False, 60.0, "needs 60.0 GB but only 9.0 GB is safely available"),
         "trace:mflux:dev": (True, 8.8, "fits"), "best-of:3:q3-30b": (True, 3.6, "fits")}


def test_a_measurement_paused_for_memory_still_runs_the_smaller_ones_that_fit(monkeypatch):
    ran, sweep = _run_loop(monkeypatch, "squeezed", lambda row: NEEDS[row["name"]])
    assert ran == ["deepen:big", "best-of:3:q3-30b", "trace:mflux:dev"]
    assert sweep.waiting == 1 and "do not fit now" in sweep.stopped and "huge: needs 60.0 GB" in sweep.stopped


def test_a_pause_another_criterion_asked_for_still_stops_the_measure_step(monkeypatch):
    ran, sweep = _run_loop(monkeypatch, "halted", lambda row: NEEDS[row["name"]])
    assert ran == ["deepen:big"]
    assert sweep.stopped.startswith("a run was paused on request: 3 measurement(s)") and sweep.waiting == 3


def test_without_a_pause_the_queue_runs_in_order_and_is_never_sized(monkeypatch):
    ran = []
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", lambda a, row, sweep=None: ran.append(row["name"]) or 0)
    monkeypatch.setattr(loop_cmd, "_beat", lambda *a, **k: None)
    rows = [{"name": n} for n in ("a", "b", "c")]

    def never(row):
        raise AssertionError("sized without a memory pause")
    loop_cmd._measure_all(None, rows, _sweep(), [], room=never)
    assert ran == ["a", "b", "c"]


# --- the ceiling left unused ----------------------------------------------------

def test_a_sweep_that_ends_early_says_how_much_ceiling_it_left_and_why():
    sweep = _sweep(4 * 3600 + 42 * 60)
    sweep.stopped, sweep.waiting = "a run was paused on request: 3 measurement(s) wait for the next sweep", 3
    got = sweep.unused()
    assert got["left_s"] == 4 * 3600 + 42 * 60 and got["waiting"] == 3 and got["why"].startswith("a run was paused")
    assert any(line.startswith("  unused: 4h 42m of the ceiling: a run was paused") for line in sweep.summary())
    assert _sweep(ceiling.UNUSED_S - 60).unused() is None
    assert _sweep().unused()["why"] == "the measure step ran out of measurements"


def _report(unused):
    beat = {"status": "finished", "rc": 0, "started": NIGHT, "finished": NIGHT + 4700, "line": "finished",
            "ceiling_unused": unused}
    conn = ms.connect()
    try:
        return morning.gather(conn, NIGHT + 36000, NIGHT - 60, beat=beat, gh=lambda argv: "[]", git=lambda argv: "",
                              lanes=lambda c: [], stalls=lambda c: [])
    finally:
        conn.close()


def test_soh_morning_names_unused_ceiling_and_asks_for_a_person_when_work_was_left(monkeypatch):
    left = {"ceiling_s": 6 * 3600.0, "left_s": 4 * 3600 + 42 * 60, "waiting": 3,
            "why": "a run was paused on request: 3 measurement(s) wait for the next sweep"}
    r = _report(left)
    want = "4h 42m of the 6h 00m sweep ceiling unused: a run was paused on request"
    assert any(n.startswith(f"the sweep left {want}") for n in r["needs"])
    assert any(line.startswith(f"ceiling   {want}") for line in morning_cmd.render(r))
    quiet = _report({**left, "waiting": 0, "why": "the measure step ran out of measurements"})
    assert not any("sweep ceiling unused" in n for n in quiet["needs"])
    assert any("sweep ceiling unused" in line for line in morning_cmd.render(quiet))
    assert not any(line.startswith("ceiling") for line in morning_cmd.render(_report(None)))


def test_the_loop_writes_the_unused_ceiling_on_its_heartbeat(monkeypatch):
    from harness import heartbeat
    heartbeat.start(total=1)
    try:
        sweep = _sweep()
        sweep.stopped, sweep.waiting = "memory: 1 measurement(s) do not fit now", 1
        monkeypatch.setattr(loop_cmd, "_loop_spend", lambda a, rc, failed, sweep: 0)
        monkeypatch.setattr(loop_cmd, "_publish_if_enabled", lambda: "")
        loop_cmd._spend_and_settle(None, 0, [], sweep)
        got = heartbeat.read()[heartbeat.CEILING_UNUSED]
        assert got["why"].startswith("memory: 1 measurement") and got["waiting"] == 1
    finally:
        heartbeat.finish(0)
