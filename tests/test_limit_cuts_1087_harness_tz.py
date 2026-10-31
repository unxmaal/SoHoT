"""The harness/t*-z* limits record a limit_cuts row when they bind and none when they do not (#1087)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import time
import types

import pytest

from harness import cuts
from harness import memory_store as ms
from harness import watchdog as wd

NOON = time.mktime((2026, 10, 12, 12, 0, 0, 0, 0, -1))
EVENING = time.mktime((2026, 10, 12, 19, 0, 0, 0, 0, -1))
NIGHT = time.mktime((2026, 10, 12, 23, 30, 0, 0, 0, -1))


def _cuts() -> list[tuple]:
    """(knob, kept, dropped) of every cut: the spool's, then the test store's."""
    path = cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    got = [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]
    if ms.db_path().exists():
        conn = sqlite3.connect(ms.db_path())
        try:
            got += [tuple(r) for r in conn.execute("SELECT knob, kept, dropped FROM limit_cuts ORDER BY id")]
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
    return got


def _knobs() -> list[str]:
    return [k for k, _, _ in _cuts()]


# --- throughput -------------------------------------------------------------------

def test_a_sweep_records_one_cut_for_its_timed_out_requests_and_none_when_all_answer():
    from harness import throughput

    def post(payload):
        if "slow" in payload["messages"][0]["content"]:
            raise TimeoutError("read timed out")
        return {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 1}}

    throughput.sweep("m", ["fast", "fast"], levels=(1, 2), post=post)
    assert _cuts() == []
    throughput.sweep("m", ["fast", "slow", "slow"], levels=(1, 2), post=post)
    assert _cuts() == [("harness/throughput.py:sweep(timeout)", None, 4)]


def test_a_ps_listing_that_times_out_is_a_cut(monkeypatch):
    from harness import throughput

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k.get("timeout"))

    monkeypatch.setattr(throughput.subprocess, "run", slow)
    with pytest.raises(subprocess.TimeoutExpired):
        throughput._descendants(1)
    assert _knobs() == ["harness/throughput.py:_descendants->subprocess.run(timeout)"]


def test_a_ps_listing_that_answers_is_no_cut(monkeypatch):
    from harness import throughput
    monkeypatch.setattr(throughput.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout="2 1\n3 2\n"))
    assert throughput._descendants(1) == [2, 3]
    assert _cuts() == []


# --- usage ------------------------------------------------------------------------

def test_rows_dropped_at_a_full_queue_are_one_cut_on_the_writer_s_store():
    from harness import usage
    conn = ms.connect()
    w = usage.Writer(connect=lambda: conn, maxsize=1)
    w.put({"at": 1.0})
    w._save_drops(conn)
    assert _cuts() == []
    w.put({"at": 2.0})
    w.put({"at": 3.0})
    w._save_drops(conn)
    assert _cuts() == [("usage_queue", None, 2)]


def test_a_writer_still_draining_at_close_is_a_cut_and_a_finished_one_is_not():
    from harness import usage
    w = usage.Writer(connect=lambda: None)
    w._thread = threading.Thread(target=lambda: None)
    w._thread.start()
    w.close(timeout=5)
    assert _cuts() == []
    release = threading.Event()
    w = usage.Writer(connect=lambda: None)
    w._thread = threading.Thread(target=release.wait, daemon=True)
    w._thread.start()
    w.close(timeout=0.01)
    release.set()
    assert _knobs() == ["harness/usage.py:Writer.close(timeout)"]


def _switch(before, after) -> dict:
    return {"switch": {"lane": "code", "id": 1, "old_spec": "a", "new_spec": "b", "switched_at": NOON},
            "sessions": {"before": before, "after": after},
            "before": {"requests": sum(s[0] for s in before), "tool_calls": 0},
            "after": {"requests": sum(s[0] for s in after), "tool_calls": 0}}


def test_a_clear_rise_on_too_few_requests_is_a_min_requests_cut():
    from harness import usage
    assert usage.regressions([_switch([[2, 0, 0, 0]] * 5, [[2, 2, 0, 0]] * 5)]) == []
    assert _cuts() == [("usage_min_requests", None, 1)]


def test_a_rise_within_noise_is_a_z_warn_cut_and_a_clear_one_warns_with_no_cut():
    from harness import usage
    noisy = usage.regressions([_switch([[10, 0, 0, 0], [10, 2, 0, 0]] * 2, [[10, 0, 0, 0], [10, 4, 0, 0]] * 2)])
    assert noisy == [] and _cuts() == [("usage_z_warn", None, 1)]
    clear = usage.regressions([_switch([[10, 0, 0, 0]] * 4, [[10, 5, 0, 0]] * 4)])
    assert len(clear) == 1 and len(_cuts()) == 1
    assert usage.regressions([_switch([[10, 1, 0, 0]] * 4, [[10, 1, 0, 0]] * 4)]) == [] and len(_cuts()) == 1


# --- vector -----------------------------------------------------------------------

@pytest.fixture
def tracer(monkeypatch, tmp_path):
    from harness.checks import render
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><path d="M0 0"/></svg>'
    fake = types.SimpleNamespace(convert_image_to_svg_py=lambda src, out, **k: open(out, "w").write(svg))
    monkeypatch.setitem(sys.modules, "vtracer", fake)
    ink = {"value": 0.5}
    monkeypatch.setattr(render, "ink", lambda s: ink["value"])

    def image(size):
        from PIL import Image
        path = tmp_path / f"in{size}.png"
        Image.new("RGB", (size, size), "white").save(path)
        return path
    return image, ink


def test_a_blank_trace_is_a_min_ink_cut_and_an_inked_one_is_not(tracer):
    from harness import vector
    image, ink = tracer
    vector.trace(image(16))
    assert _cuts() == []
    ink["value"] = 0.0
    with pytest.raises(vector.VectorError):
        vector.trace(image(16))
    assert _cuts() == [("harness/vector.py:MIN_INK", 0, 1)]


def test_the_icon_preset_shrinking_a_larger_image_is_a_cut_and_a_small_one_is_not(tracer):
    from harness import vector
    image, _ = tracer
    at = vector.TRACE_PRESETS["icon"]["trace_at"]
    vector.trace(image(at // 2), preset="icon")
    vector.trace(image(at * 2), preset="illustration")
    assert _cuts() == []
    vector.trace(image(at * 2), preset="icon")
    assert _knobs() == ["harness/vector.py:TRACE_PRESETS[icon][trace_at]"]


# --- vllm -------------------------------------------------------------------------

def _exits_with(tmp_path, text: str):
    from harness import vllm
    cmd = [sys.executable, "-c", f"print({text!r})", "--gpu-memory-utilization", "0.2"]
    with pytest.raises(RuntimeError):
        with vllm.served(cmd, 9, tmp_path / "log.txt", timeout=30, poll=0.05):
            pass


def test_a_server_with_no_room_for_its_kv_cache_is_a_memory_fraction_cut(tmp_path):
    _exits_with(tmp_path, "ImportError: no module named vllm")
    assert _cuts() == []
    _exits_with(tmp_path, "ValueError: No available memory for the cache blocks. Try increasing "
                          "`gpu_memory_utilization` when initializing the engine.")
    assert _knobs() == ["harness/vllm.py:METAL_MEMORY_FRACTION"]


# --- workqueue --------------------------------------------------------------------

def test_a_git_call_that_times_out_is_a_cut_and_reads_as_no_answer(monkeypatch, tmp_path):
    from harness import workqueue

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k.get("timeout"))

    assert workqueue._git(tmp_path, "rev-parse", "HEAD") is None
    assert _cuts() == []
    monkeypatch.setattr(workqueue.subprocess, "run", slow)
    assert workqueue._git(tmp_path, "rev-parse", "HEAD") is None
    assert _knobs() == ["harness/workqueue.py:_git->subprocess.run(timeout)"]


# --- watchdog judges --------------------------------------------------------------

def _eval(done=10, planned=10.0, observed=10.0, last=None, now=NIGHT, key="eval pgid 500"):
    run = {"state": "running", "done": done, "total": 100, "specs": {"a": "llamacpp:a"},
           "planned_s_per_case": {"a": planned}, "observed_s_per_case": {"a": observed},
           "started_at": now - 3600, "last_progress_at": now - 60 if last is None else last}
    return wd.Subject("eval", key, "test", pid=500, pgid=500, elapsed_s=600.0, command="evals.run", progress=run)


def test_overrun_past_the_factor_is_a_cut_and_within_it_is_not():
    assert wd._overrun(wd.World(now=NIGHT, evals=[_eval(observed=15.0)])) == []
    assert _cuts() == []
    assert len(wd._overrun(wd.World(now=NIGHT, evals=[_eval(observed=30.0)]))) == 1
    assert _cuts() == [("watchdog_overrun_factor", None, 1)]


def test_an_overrun_held_back_for_too_few_cases_is_a_min_cases_cut():
    assert wd._overrun(wd.World(now=NIGHT, evals=[_eval(done=1, observed=10.0)])) == []
    assert _cuts() == []
    assert wd._overrun(wd.World(now=NIGHT, evals=[_eval(done=1, observed=30.0)])) == []
    assert _cuts() == [("watchdog_overrun_min_cases", 1, None)]


def test_a_slow_challenger_held_back_for_too_few_pairs_is_a_min_pairs_cut(monkeypatch):
    def paired(n):
        cases = [f"c{i}" for i in range(n)]
        return ("inc", {"inc": {c: [10.0, None, 1] for c in cases}, "ch": {c: [30.0, None, 1] for c in cases}})

    s = _eval()
    s.progress.update({"planned_s_per_case": {"inc": 10.0, "ch": 10.0},
                       "observed_s_per_case": {"inc": 10.0, "ch": 30.0}})
    monkeypatch.setattr(wd, "_cells", lambda run: paired(wd.OVERRUN_MIN_PAIRS - 1))
    assert wd._overrun(wd.World(now=NIGHT, evals=[s])) == []
    assert _cuts() == [("watchdog_overrun_min_pairs", 1, None)]
    monkeypatch.setattr(wd, "_cells", lambda run: paired(wd.OVERRUN_MIN_PAIRS))
    assert len(wd._overrun(wd.World(now=NIGHT, evals=[s]))) == 1
    assert _knobs() == ["watchdog_overrun_min_pairs", "watchdog_overrun_factor"]


def test_no_progress_names_the_limit_that_set_the_stall():
    assert wd._no_progress(wd.World(now=NIGHT, evals=[_eval(last=NIGHT - wd.STALL_S + 60)])) == []
    assert _cuts() == []
    assert len(wd._no_progress(wd.World(now=NIGHT, evals=[_eval(last=NIGHT - wd.STALL_S - 60)]))) == 1
    slow = _eval(planned=wd.STALL_S, last=NIGHT - wd.STALL_CASES * wd.STALL_S - 60)
    assert len(wd._no_progress(wd.World(now=NIGHT, evals=[slow]))) == 1
    assert _cuts() == [("watchdog_stall", None, 1), ("watchdog_stall_cases", None, 1)]


def _orphan(elapsed):
    return wd.Subject("eval", f"eval pgid {int(elapsed)}", "test", pid=9, pgid=9, elapsed_s=float(elapsed), orphan=True)


def test_an_orphan_inside_the_grace_is_a_cut_and_one_past_it_is_reaped_with_none():
    assert len(wd._orphan(wd.World(now=NIGHT, top=[_orphan(wd.ORPHAN_GRACE_S + 1)]))) == 1
    assert _cuts() == []
    assert wd._orphan(wd.World(now=NIGHT, top=[_orphan(1)])) == []
    assert _cuts() == [("watchdog_orphan_grace", 1, None)]


def test_stale_mcp_servers_inside_the_grace_are_a_cut():
    stale = [wd.Subject("mcp", "mcp pid 7", "test", pid=7)]
    assert wd._stale_mcp(wd.World(now=NIGHT, mcp_live_s=1.0)) == []
    assert _cuts() == []
    assert wd._stale_mcp(wd.World(now=NIGHT, mcp_live_s=1.0, mcp_stale=stale)) == []
    assert _cuts() == [("watchdog_orphan_grace", 1, None)]


def _gpu_job(elapsed):
    return wd.Subject("job", "job 0007", "test", pid=5, pgid=5, elapsed_s=float(elapsed))


@pytest.mark.parametrize("now, edge", [(NOON, "watchdog_day_start_hour"), (EVENING, "watchdog_day_end_hour")])
def test_a_gpu_job_past_the_day_limit_is_a_cut_with_the_nearer_day_edge(now, edge):
    if not wd.daytime(now):
        pytest.skip("the default day hours moved")
    long = wd.World(now=now, top=[_gpu_job(wd.DAYTIME_GPU_S + 1)], gpu="job 0007")
    assert wd._daytime_gpu(wd.World(now=now, top=[_gpu_job(60)], gpu="job 0007")) == []
    assert wd._daytime_gpu(wd.World(now=NIGHT, top=[_gpu_job(wd.DAYTIME_GPU_S + 1)], gpu="job 0007")) == []
    assert _cuts() == []
    assert len(wd._daytime_gpu(long)) == 1
    assert _cuts() == [("watchdog_daytime_gpu", None, 1), (edge, None, 1)]


def test_an_old_idle_lock_is_a_cut_and_a_young_one_is_not():
    assert wd._idle_lock(wd.World(now=NIGHT, lock={"pid": 3, "since": NIGHT - 10})) == []
    assert _cuts() == []
    assert len(wd._idle_lock(wd.World(now=NIGHT, lock={"pid": 3, "since": NIGHT - wd.IDLE_HOLD_S - 1}))) == 1
    assert _cuts() == [("watchdog_idle_hold", None, 1)]


def test_swapping_is_a_cut_unless_critical_pressure_trips_it_anyway():
    from harness import pressure
    job = [_gpu_job(60)]
    calm = types.SimpleNamespace(level=pressure.NORMAL, alarming=False)
    assert wd._memory(wd.World(now=NIGHT, top=job, pressure=calm, swap_per_min=1.0)) == []
    critical = types.SimpleNamespace(level=pressure.CRITICAL, alarming=True)
    assert len(wd._memory(wd.World(now=NIGHT, top=job, pressure=critical, swap_per_min=1e9))) == 1
    assert _cuts() == []
    assert len(wd._memory(wd.World(now=NIGHT, top=job, pressure=calm, swap_per_min=wd.SWAPOUT_MAX_PER_MIN + 1))) == 1
    assert _cuts() == [("watchdog_swapout_max", None, 1)]


def test_an_idle_model_given_back_in_the_day_is_a_cut():
    served = [{"server": "router", "model": "m", "in_flight": False}]
    idle = {"router:m": NOON - wd.IDLE_UNLOAD_DAY_S - 1}
    assert wd._idle_unload(wd.World(now=NOON, served=served, idle_since={"router:m": NOON - 1})) == []
    assert _cuts() == []
    assert len(wd._idle_unload(wd.World(now=NOON, served=served, idle_since=idle))) == 1
    assert _cuts() == [("serve_idle_unload_day_s", None, 1)]


def test_a_fallback_spike_is_a_cut_and_fewer_requests_are_not():
    few = [{"node": "a", "requests": wd.FALLBACK_MAX - 1}]
    assert wd._node_fallbacks(wd.World(now=NIGHT, fallbacks=few)) == []
    assert _cuts() == []
    assert len(wd._node_fallbacks(wd.World(now=NIGHT, fallbacks=[{"node": "a", "requests": wd.FALLBACK_MAX}]))) == 1
    assert _cuts() == [("watchdog_fallback_max", None, 1)]


# --- watchdog wake ----------------------------------------------------------------

class _Probes(wd.Probes):
    def __init__(self, tmp_path, procs=(), fallbacks=None):
        self.tmp, self.procs, self._fallbacks = tmp_path, list(procs), fallbacks or []

    def processes(self):
        return self.procs

    def launchd_pid(self, service):
        return None

    def heartbeat(self):
        return None

    def job_pids(self):
        return {}

    def job(self, job_id):
        return {"state": "running", "title": "t"}

    def worker_running(self):
        return True

    def progress(self, evals):
        return []

    def lock(self):
        return {}

    def resident(self):
        return []

    def pressure(self):
        return types.SimpleNamespace(level=1, alarming=False, swapouts=None)

    def gateway_up(self):
        return None

    def mlx_generating(self):
        return None

    def fallbacks(self, conn):
        return self._fallbacks

    def mcp_connections(self, port):
        return None

    def state(self):
        d = self.tmp / "wd"
        d.mkdir(exist_ok=True)
        return d


class _Hand(wd.Hands):
    def __init__(self):
        super().__init__(run=None, environ={})

    def do(self, action, f):
        return "ok"


def _orphan_proc():
    return wd.Proc(900, 1, 900, 600.0, "/usr/bin/python3 -m evals.run --modality code --candidates a")


def test_an_escalation_is_a_cut_and_trips_outside_the_window_are_a_window_cut(tmp_path):
    conn = ms.connect()
    probes = _Probes(tmp_path, procs=[_orphan_proc()])
    for i in range(wd.ESCALATE_AFTER):
        wd.wake(conn, probes, _Hand(), act=True, now=NIGHT + i * (wd.ESCALATE_WINDOW_S + 1), say=lambda *_: None)
    assert [k for k in _knobs() if k.startswith("watchdog_escalate")] == []
    wd.wake(conn, probes, _Hand(), act=True, now=NIGHT + wd.ESCALATE_AFTER * (wd.ESCALATE_WINDOW_S + 1),
            say=lambda *_: None)
    assert [k for k in _knobs() if k.startswith("watchdog_escalate")] == ["watchdog_escalate_window"]
    for i in range(1, wd.ESCALATE_AFTER + 1):
        wd.wake(conn, probes, _Hand(), act=True, now=NIGHT + wd.ESCALATE_AFTER * (wd.ESCALATE_WINDOW_S + 1) + i,
                say=lambda *_: None)
    assert [k for k in _knobs() if k.startswith("watchdog_escalate")][-1] == "watchdog_escalate_after"


class _Notifier(_Hand):
    def notify(self, f):
        return f"{wd.NOTIFIED}: shown"


def test_a_notification_held_inside_the_interval_is_one_cut_per_wake(tmp_path, monkeypatch):
    monkeypatch.setattr(wd, "ESCALATE_AFTER", 99)
    conn = ms.connect()
    probes = _Probes(tmp_path, fallbacks=[{"node": n, "requests": wd.FALLBACK_MAX} for n in "ab"])
    hand = _Notifier()
    hand.do = lambda action, f: hand.notify(f)
    wd.wake(conn, probes, hand, act=True, now=NIGHT, say=lambda *_: None)
    assert "watchdog_notify_every" not in _knobs()
    wd.wake(conn, probes, hand, act=True, now=NIGHT + 300, say=lambda *_: None)
    assert [c for c in _cuts() if c[0] == "watchdog_notify_every"] == [("watchdog_notify_every", None, 2)]
