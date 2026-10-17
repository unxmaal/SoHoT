"""The watchdog: each criterion trips on a fake job built to trip it and stays quiet on one that should not; each action against a fake (#814)."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import memory_store as ms
from harness import watchdog as wd

#: A fixed local noon and midnight, so day hours never depend on when the suite runs.
NOON = time.mktime((2026, 10, 12, 12, 0, 0, 0, 0, -1))
NIGHT = time.mktime((2026, 10, 12, 23, 30, 0, 0, 0, -1))
EVAL = "/usr/bin/python3 -m evals.run --modality code --candidates a"


class Fake(wd.Probes):
    def __init__(self, tmp_path, procs=(), discover=None, beat=None, jobs=None, rows=None, worker=True,
                 progress=(), lock=None, resident=None, pressure=None, gateway=None, fallbacks=None, mlx=None):
        self.tmp, self.procs, self.discover, self.beat = tmp_path, list(procs), discover, beat
        self.jobs, self.rows, self.worker = jobs or {}, rows or {}, worker
        self.runs, self._lock, self._resident = list(progress), lock if lock is not None else {}, resident
        self._pressure, self._gateway, self._fallbacks, self._mlx = pressure, gateway, fallbacks, mlx

    def processes(self):
        return self.procs

    def launchd_pid(self, service):
        return self.discover if service == "discover" else None

    def heartbeat(self):
        return self.beat

    def job_pids(self):
        return self.jobs

    def job(self, job_id):
        return self.rows.get(job_id, {"state": "running", "title": "t"})

    def worker_running(self):
        return self.worker

    def progress(self, evals):
        return self.runs

    def lock(self):
        return self._lock

    def resident(self):
        return self._resident if self._resident is not None else []

    def pressure(self):
        return self._pressure or Pressure()

    def gateway_up(self):
        return self._gateway

    def mlx_generating(self):
        return self._mlx

    def fallbacks(self, conn):
        return self._fallbacks if self._fallbacks is not None else []

    def state(self):
        d = self.tmp / "wd"
        d.mkdir(exist_ok=True)
        return d


class Pressure:
    def __init__(self, level=1, alarming=False, swapouts=None):
        self.level, self.alarming, self.swapouts = level, alarming, swapouts


def P(pid, ppid, pgid, elapsed, command):
    return wd.Proc(pid, ppid, pgid, float(elapsed), command)


def run(pid, done=10, planned=10.0, observed=10.0, last=None, now=NIGHT, tmp=None):
    got = {"state": "running", "pid": pid, "done": done, "total": 100, "specs": {"a": "llamacpp:a"},
           "planned_s_per_case": {"a": planned}, "observed_s_per_case": {"a": observed},
           "started_at": now - 3600, "last_progress_at": now - 60 if last is None else last}
    if tmp is not None:
        got.update({"_dir": str(tmp), "pause_file": str(tmp / "pause")})
    return got


def judged(fake, now=NIGHT):
    world = wd.observe(fake, None, now)
    found, skipped = wd.judge(world)
    return world, found, skipped


def ids(found, criterion):
    return [f.subject.key for f in found if f.criterion == criterion]


def owned_eval(tmp_path, elapsed=60, progress=(), now=NIGHT):
    """A queue job 0007 (group 500) running an evals.run (group 510, its own session)."""
    return Fake(tmp_path, procs=[P(500, 400, 500, elapsed, "uv run soh discover --loop"),
                                 P(510, 500, 510, elapsed, "uv run python -m evals.run --modality code"),
                                 P(511, 510, 510, elapsed, EVAL)],
                jobs={"0007": 500}, progress=progress)


# --- identification ------------------------------------------------------------

def test_an_eval_under_a_queue_job_is_that_job_s_child_and_not_a_top_level_subject(tmp_path):
    world, _, _ = judged(owned_eval(tmp_path))
    assert [s.key for s in world.top] == ["job 0007"]
    assert [c.key for c in world.top[0].children] == ["eval pgid 510"]
    assert world.evals[0].owner == "job 0007" and world.evals[0].pgid == 510


def test_an_eval_a_person_started_in_a_terminal_is_left_alone(tmp_path):
    fake = Fake(tmp_path, procs=[P(300, 1, 300, 99999, "-zsh"), P(310, 300, 310, 99999, EVAL)])
    world, found, _ = judged(fake)
    assert not world.evals and [s.pid for s in world.unowned] == [310]
    assert not found, "an eval that is not provably SoHoT's is never judged"


def test_the_discover_agent_is_identified_by_launchd_pid_and_its_command(tmp_path):
    fake = Fake(tmp_path, procs=[P(700, 1, 700, 60, "/bin/bash /x/serve-discover.sh")], discover=700)
    assert [s.key for s in judged(fake)[0].top] == ["discover pid 700"]
    impostor = Fake(tmp_path, procs=[P(700, 1, 700, 60, "/usr/bin/vim notes")], discover=700)
    assert judged(impostor)[0].top == [], "a pid launchd names that runs something else is not ours"


def test_a_group_with_anything_but_evals_in_it_cannot_be_signalled(tmp_path):
    fake = Fake(tmp_path, procs=[P(800, 1, 800, 600, EVAL), P(801, 800, 800, 600, "/usr/bin/vim")],
                progress=[run(800)])
    world, _, _ = judged(fake)
    assert world.evals[0].pgid is None


# --- criteria: each red on a job built to trip it, green on one that should not --

def test_long_run_trips_past_the_night_limit_and_not_before(tmp_path):
    long = owned_eval(tmp_path, elapsed=wd.LONG_RUN_S + 60)
    short = owned_eval(tmp_path, elapsed=wd.LONG_RUN_S - 60)
    assert ids(judged(long)[1], "long_run") == ["job 0007"]
    assert ids(judged(short)[1], "long_run") == []


def test_long_run_is_tighter_during_the_day(tmp_path):
    fake = owned_eval(tmp_path, elapsed=wd.LONG_RUN_DAY_S + 60)
    assert ids(judged(fake, NOON)[1], "long_run") == ["job 0007"]
    assert ids(judged(fake, NIGHT)[1], "long_run") == []


def test_overrun_trips_at_the_factor_over_plan_and_not_under_it(tmp_path):
    slow = owned_eval(tmp_path, progress=[run(511, planned=10.0, observed=10.0 * wd.OVERRUN_FACTOR + 1)])
    fine = owned_eval(tmp_path, progress=[run(511, planned=10.0, observed=10.0 * wd.OVERRUN_FACTOR - 1)])
    found = judged(slow)[1]
    assert ids(found, "overrun") == ["eval pgid 510"]
    assert found[0].evidence["candidate"] == "a"
    assert ids(judged(fine)[1], "overrun") == []


def test_overrun_waits_for_enough_cases(tmp_path):
    early = owned_eval(tmp_path, progress=[run(511, done=wd.OVERRUN_MIN_CASES - 1, observed=1000.0)])
    assert ids(judged(early)[1], "overrun") == []


def test_no_progress_trips_when_no_case_finished_for_the_stall_time(tmp_path):
    stuck = owned_eval(tmp_path, progress=[run(511, last=NIGHT - wd.STALL_S - 60)])
    moving = owned_eval(tmp_path, progress=[run(511, last=NIGHT - 60)])
    assert ids(judged(stuck)[1], "no_progress") == ["eval pgid 510"]
    assert ids(judged(moving)[1], "no_progress") == []


def test_no_progress_allows_a_slow_plan_its_planned_cases(tmp_path):
    slow_plan = 2 * wd.STALL_S / wd.STALL_CASES
    fake = owned_eval(tmp_path, progress=[run(511, planned=slow_plan, observed=slow_plan, last=NIGHT - wd.STALL_S - 60)])
    assert ids(judged(fake)[1], "no_progress") == []


def test_criteria_that_need_a_progress_file_are_skipped_and_say_so_without_one(tmp_path):
    _, found, skipped = judged(owned_eval(tmp_path))
    assert "progress file" in skipped["overrun"] and "progress file" in skipped["no_progress"]
    assert "long_run" not in skipped


def test_an_eval_reparented_to_launchd_is_an_orphan_once_past_the_grace(tmp_path):
    old = Fake(tmp_path, procs=[P(900, 1, 900, wd.ORPHAN_GRACE_S + 5, EVAL)])
    young = Fake(tmp_path, procs=[P(900, 1, 900, wd.ORPHAN_GRACE_S - 5, EVAL)])
    assert ids(judged(old)[1], "orphan") == ["eval pgid 900"]
    assert ids(judged(young)[1], "orphan") == []


def test_a_queue_job_with_no_worker_or_a_settled_row_is_an_orphan(tmp_path):
    procs = [P(500, 1, 500, 600, "uv run soh image")]
    assert ids(judged(Fake(tmp_path, procs=procs, jobs={"0007": 500}, worker=False))[1], "orphan") == ["job 0007"]
    cancelled = Fake(tmp_path, procs=procs, jobs={"0007": 500}, rows={"0007": {"state": "cancelled"}})
    assert ids(judged(cancelled)[1], "orphan") == ["job 0007"]
    assert ids(judged(Fake(tmp_path, procs=procs, jobs={"0007": 500}))[1], "orphan") == []


def test_daytime_gpu_trips_inside_the_day_and_not_at_night(tmp_path):
    fake = owned_eval(tmp_path, elapsed=wd.DAYTIME_GPU_S + 60)
    assert ids(judged(fake, NOON)[1], "daytime_gpu") == ["job 0007"]
    assert ids(judged(fake, NIGHT)[1], "daytime_gpu") == []
    short = owned_eval(tmp_path, elapsed=wd.DAYTIME_GPU_S - 60)
    assert ids(judged(short, NOON)[1], "daytime_gpu") == []


def test_idle_lock_trips_only_when_nothing_runs_and_it_is_old(tmp_path):
    held = {"kind": "image", "pid": 42, "since": NIGHT - wd.IDLE_HOLD_S - 60}
    assert ids(judged(Fake(tmp_path, lock=held))[1], "idle_lock") == ["lock pid 42"]
    fresh = {**held, "since": NIGHT - 60}
    assert ids(judged(Fake(tmp_path, lock=fresh))[1], "idle_lock") == []
    busy = owned_eval(tmp_path)
    busy._lock = held
    assert ids(judged(busy)[1], "idle_lock") == []


def test_idle_model_trips_on_an_unprotected_resident_model_with_nothing_running(tmp_path):
    assert ids(judged(Fake(tmp_path, resident=["junk"]))[1], "idle_model") == ["model junk"]
    busy = owned_eval(tmp_path)
    busy._resident = ["junk"]
    assert ids(judged(busy)[1], "idle_model") == []
    assert ids(judged(Fake(tmp_path, resident=[]))[1], "idle_model") == []


def test_memory_trips_on_alarming_pressure_while_a_job_runs(tmp_path):
    fake = owned_eval(tmp_path)
    fake._pressure = Pressure(level=4, alarming=True)
    assert ids(judged(fake)[1], "memory") == ["job 0007"]
    idle = Fake(tmp_path, pressure=Pressure(level=4, alarming=True))
    assert ids(judged(idle)[1], "memory") == [], "pressure with nothing of ours running is not ours to act on"
    calm = owned_eval(tmp_path)
    assert ids(judged(calm)[1], "memory") == []


def test_memory_trips_on_swap_growth_between_wakes(tmp_path):
    fake = owned_eval(tmp_path)
    fake._pressure = Pressure(swapouts=1000)
    assert ids(judged(fake, NIGHT - 60)[1], "memory") == []
    fake._pressure = Pressure(swapouts=1000 + int(wd.SWAPOUT_MAX_PER_MIN) * 2)
    assert ids(judged(fake, NIGHT)[1], "memory") == ["job 0007"]
    fake._pressure = Pressure(swapouts=1000 + int(wd.SWAPOUT_MAX_PER_MIN) * 2 + 10)
    assert ids(judged(fake, NIGHT + 60)[1], "memory") == []


def test_gateway_down_trips_only_on_a_failed_probe(tmp_path):
    assert ids(judged(Fake(tmp_path, gateway=False))[1], "gateway_down") == ["gateway"]
    assert ids(judged(Fake(tmp_path, gateway=True))[1], "gateway_down") == []
    _, _, skipped = judged(Fake(tmp_path, gateway=None))
    assert "gateway_down" in skipped


def test_node_fallbacks_trip_at_the_limit(tmp_path):
    over = [{"node": "khryll", "requests": wd.FALLBACK_MAX, "aliases": ["sohot-code"]}]
    under = [{"node": "khryll", "requests": wd.FALLBACK_MAX - 1, "aliases": []}]
    assert ids(judged(Fake(tmp_path, fallbacks=over))[1], "node_fallbacks") == ["node khryll"]
    assert ids(judged(Fake(tmp_path, fallbacks=under))[1], "node_fallbacks") == []


def test_every_criterion_maps_to_actions_from_the_fixed_set_and_names_registered_knobs():
    from harness import knobs
    assert len({c.id for c in wd.CRITERIA}) == len(wd.CRITERIA)
    for c in wd.CRITERIA:
        assert c.action in wd.ACTIONS and c.escalation in wd.ACTIONS, c.id
        assert c.action != c.escalation, c.id
        for k in c.knobs:
            assert k in knobs.KNOBS, (c.id, k)
    assert set(wd.ACTIONS) <= {c.action for c in wd.CRITERIA} | {c.escalation for c in wd.CRITERIA}


# --- actions -------------------------------------------------------------------

def finding(criterion="overrun", **kw):
    s = wd.Subject("eval", "eval pgid 1", "test", **kw)
    return wd.Finding(criterion, s, {"x": 1})


def test_note_records_without_touching_anything():
    assert wd.Hands(run=None).do(wd.NOTE, finding()) == "noted"


def _osascript(rc=0, stderr=""):
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, "", stderr)
    return calls, fake


def test_notify_posts_a_desktop_notification_naming_the_criterion_and_target():
    calls, fake = _osascript()
    out = wd.Hands(run=fake, platform="darwin").do(wd.NOTIFY, finding("long_run"))
    assert out == "notified: long_run: eval pgid 1"
    cmd = calls[0]
    assert cmd[0] == "osascript" and "display notification" in " ".join(cmd)
    assert cmd[-3:] == [wd.NOTIFY_TITLE, "long_run: eval pgid 1", wd.BY_ID["long_run"].what]


def test_notify_passes_the_subject_as_argv_so_quotes_cannot_break_the_script():
    calls, fake = _osascript()
    f = wd.Finding("long_run", wd.Subject("eval", 'eval "x" & do shell script "rm"', "t"), {})
    wd.Hands(run=fake, platform="darwin").do(wd.NOTIFY, f)
    assert all("rm" not in part for part in calls[0][:-3])


def test_notify_says_why_when_osascript_fails_or_hangs():
    _, fake = _osascript(rc=1, stderr="execution error")
    assert wd.Hands(run=fake, platform="darwin").do(wd.NOTIFY, finding()).startswith("notify failed: osascript rc 1")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    assert wd.Hands(run=slow, platform="darwin").do(wd.NOTIFY, finding()).startswith("notify failed")


@pytest.mark.parametrize("plat", ["win32", "linux"])
def test_notify_is_unavailable_off_macos_and_says_why(plat):
    calls, fake = _osascript()
    out = wd.Hands(run=fake, platform=plat).do(wd.NOTIFY, finding())
    assert out.startswith("notify unavailable") and plat in out and calls == []


def test_pause_writes_the_pause_file_in_the_run_directory(tmp_path):
    f = finding(progress=run(1, tmp=tmp_path))
    out = wd.Hands().do(wd.PAUSE, f)
    assert (tmp_path / "pause").is_file() and "pause file written" in out


def test_pause_refuses_a_pause_file_outside_the_run_directory(tmp_path):
    bad = {**run(1, tmp=tmp_path), "pause_file": str(tmp_path.parent / "elsewhere")}
    assert wd.Hands().do(wd.PAUSE, finding(progress=bad)).startswith("refused")
    assert not (tmp_path.parent / "elsewhere").exists()


def test_pause_without_a_progress_file_says_it_is_unavailable():
    assert "unavailable" in wd.Hands().do(wd.PAUSE, finding())


def test_pause_of_a_job_pauses_each_eval_under_it(tmp_path):
    child = wd.Subject("eval", "eval pgid 2", "t", progress=run(2, tmp=tmp_path))
    job = wd.Subject("job", "job 0007", "t", children=[child])
    wd.Hands().do(wd.PAUSE, wd.Finding("long_run", job, {}))
    assert (tmp_path / "pause").is_file()


def _group(tmp_path):
    """A sleeping child leading its own group, reaped as it exits as its real parent would reap it."""
    import threading
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
    threading.Thread(target=proc.wait, daemon=True).start()
    return proc


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX process group")
def test_stop_terminates_a_fake_process_group(tmp_path):
    proc = _group(tmp_path)
    try:
        out = wd.Hands().do(wd.STOP, finding(pgid=proc.pid))
        assert proc.wait(timeout=30) is not None and out == f"group {proc.pid}: term"
    finally:
        proc.kill()


def test_stop_refuses_a_subject_with_no_group_of_ours():
    assert wd.Hands().do(wd.STOP, finding(pgid=None)).startswith("refused")


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX process group")
def test_reap_kills_an_orphan_group_and_refuses_one_that_is_not(tmp_path):
    proc = _group(tmp_path)
    try:
        assert wd.Hands().do(wd.REAP, finding(pgid=proc.pid)).startswith("refused")
        assert proc.poll() is None
        assert wd.Hands().do(wd.REAP, finding(pgid=proc.pid, orphan=True)) == f"group {proc.pid}: term"
        proc.wait(timeout=30)
    finally:
        proc.kill()


def test_unload_goes_through_the_router_s_own_protection(monkeypatch):
    from harness import router
    asked = []
    monkeypatch.setattr(router, "release", lambda stems, why, say=print: asked.append(stems) or stems)
    f = wd.Finding("idle_model", wd.Subject("model", "model junk", "t", detail={"stem": "junk"}), {})
    assert wd.Hands().do(wd.UNLOAD, f) == "unloaded junk" and asked == [["junk"]]
    monkeypatch.setattr(router, "release", lambda stems, why, say=print: [])
    assert wd.Hands().do(wd.UNLOAD, f).startswith("kept")


def test_restart_runs_launchd_restart_for_the_gateway_and_refuses_an_unlisted_service():
    calls = []

    def fake(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    g = wd.Finding("gateway_down", wd.Subject("gateway", "gateway", "t", detail={"service": "gateway"}), {})
    assert wd.Hands(run=fake).do(wd.RESTART, g) == "restarted gateway"
    assert calls[0][-2:] == ["restart", "gateway"] and Path(calls[0][1]).as_posix().endswith("scripts/launchd.sh")
    other = wd.Finding("x", wd.Subject("model", "m", "t", detail={"service": "tts"}), {})
    assert wd.Hands(run=fake).do(wd.RESTART, other).startswith("refused") and len(calls) == 1


def test_restart_that_waits_on_the_gpu_lock_says_so():
    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
    g = wd.Finding("gateway_down", wd.Subject("gateway", "gateway", "t", detail={"service": "gateway"}), {})
    assert "still waiting" in wd.Hands(run=slow).do(wd.RESTART, g)


def _gh(open_issues):
    calls = []

    def fake(argv, **kw):
        calls.append(argv)
        if argv[:3] == ["gh", "issue", "list"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(open_issues), "")
        return subprocess.CompletedProcess(argv, 0, "https://github.com/x/y/issues/9\n", "")
    return calls, fake


def test_file_is_off_until_its_own_switch_is_set():
    calls, fake = _gh([])
    assert wd.Hands(run=fake, environ={}).do(wd.FILE, finding()).startswith("not filed")
    assert calls == []


def test_file_creates_an_issue_carrying_its_fingerprint():
    calls, fake = _gh([])
    f = finding(command=EVAL)
    out = wd.Hands(run=fake, environ={wd.FILE_ENV: "1"}).do(wd.FILE, f)
    assert out.startswith("filed") and calls[1][:3] == ["gh", "issue", "create"]
    assert f"{wd.FINGERPRINT} {wd.fingerprint(f)}" in calls[1][calls[1].index("--body") + 1]


def test_file_is_deduped_against_an_open_issue_with_the_fingerprint():
    calls, fake = _gh([{"number": 812}])
    assert wd.Hands(run=fake, environ={wd.FILE_ENV: "1"}).do(wd.FILE, finding()) == "already filed: #812"
    assert len(calls) == 1 and wd.fingerprint(finding()) in calls[0][calls[0].index("--search") + 1]


def test_the_fingerprint_survives_a_new_pid_and_changes_with_the_criterion():
    a = wd.Finding("overrun", wd.Subject("eval", "eval pgid 1", "t", command="python -m evals.run --x 1 pid 11"), {})
    b = wd.Finding("overrun", wd.Subject("eval", "eval pgid 2", "t", command="python -m evals.run --x 2 pid 22"), {})
    c = wd.Finding("no_progress", a.subject, {})
    assert wd.fingerprint(a) == wd.fingerprint(b) != wd.fingerprint(c)


def test_an_action_outside_the_fixed_set_is_refused():
    with pytest.raises(ValueError):
        wd.Hands().do("format_disk", finding())


# --- a wake: dry run by default, records every act, escalates on repeat -------

class Hand(wd.Hands):
    def __init__(self):
        super().__init__(run=None, environ={})
        self.done = []

    def do(self, action, f):
        self.done.append((action, f.subject.key))
        return "ok"


def _rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM watchdog_actions ORDER BY id")]


def test_a_dry_run_records_what_it_would_do_and_does_nothing(tmp_path):
    conn = ms.connect()
    hand, said = Hand(), []
    fake = Fake(tmp_path, procs=[P(900, 1, 900, 600, EVAL)])
    got = wd.wake(conn, fake, hand, act=False, now=NIGHT, say=said.append)
    assert hand.done == [] and got["acted"][0]["outcome"] == "dry-run"
    rows = _rows(conn)
    assert [(r["criterion"], r["action"], r["dry_run"]) for r in rows] == [("orphan", "reap", 1)]
    ev = json.loads(rows[0]["evidence"])
    assert ev["identified_by"] and ev["pgid"] == 900 and ev["fingerprint"]
    assert any(line.startswith("[dry-run] would reap") for line in said)


def test_acting_records_the_outcome_and_escalates_on_repeat(tmp_path):
    conn = ms.connect()
    hand = Hand()
    fake = Fake(tmp_path, procs=[P(900, 1, 900, 600, EVAL)])
    for i in range(wd.ESCALATE_AFTER + 1):
        wd.wake(conn, fake, hand, act=True, now=NIGHT + i, say=lambda *_: None)
    assert [a for a, _ in hand.done] == [wd.REAP] * wd.ESCALATE_AFTER + [wd.FILE]
    rows = _rows(conn)
    assert [r["escalated"] for r in rows] == [0] * wd.ESCALATE_AFTER + [1]
    assert all(r["outcome"] == "ok" and r["dry_run"] == 0 for r in rows)


def test_trips_outside_the_window_do_not_escalate(tmp_path):
    conn = ms.connect()
    hand = Hand()
    fake = Fake(tmp_path, procs=[P(900, 1, 900, 600, EVAL)])
    for i in range(wd.ESCALATE_AFTER + 1):
        wd.wake(conn, fake, hand, act=True, now=NIGHT + i * (wd.ESCALATE_WINDOW_S + 1), say=lambda *_: None)
    assert [a for a, _ in hand.done] == [wd.REAP] * (wd.ESCALATE_AFTER + 1)


def test_dry_run_trips_never_escalate_a_real_action(tmp_path):
    conn = ms.connect()
    fake = Fake(tmp_path, procs=[P(900, 1, 900, 600, EVAL)])
    for i in range(wd.ESCALATE_AFTER + 1):
        wd.wake(conn, fake, Hand(), act=False, now=NIGHT + i, say=lambda *_: None)
    hand = Hand()
    wd.wake(conn, fake, hand, act=True, now=NIGHT + 10, say=lambda *_: None)
    assert hand.done == [(wd.REAP, "eval pgid 900")]


def test_a_second_wake_while_one_holds_the_lock_does_nothing(tmp_path):
    from harness import exclusive
    import os
    conn = ms.connect()
    fake = Fake(tmp_path, procs=[P(900, 1, 900, 600, EVAL)])
    fd = os.open(fake.state() / "lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        assert exclusive._take(fd)
        assert wd.wake(conn, fake, Hand(), act=True, now=NIGHT, say=lambda *_: None)["busy"]
    finally:
        exclusive._release(fd)
        os.close(fd)
    assert _rows(conn) == []


def test_acting_needs_the_env_switch_or_the_flag():
    assert not wd.acting({})
    assert not wd.acting({wd.ACT_ENV: "yes"})
    assert wd.acting({wd.ACT_ENV: "1"})


def test_ps_output_parses_elapsed_times_in_every_form():
    got = wd.parse_ps(" 12   1  12 01:02 python -m evals.run\n 13 12 12 1-02:03:04 sleep 1\nbad line\n")
    assert [(p.pid, p.elapsed_s) for p in got] == [(12, 62.0), (13, 86400 + 7384.0)]


def test_progress_files_are_read_from_run_directories_and_only_while_running(tmp_path):
    for name, state in (("a", "running"), ("b", "done")):
        d = tmp_path / name
        d.mkdir()
        (d / "progress.json").write_text(json.dumps({"state": state, "pid": 1}), encoding="utf-8")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "progress.json").write_text("{torn", encoding="utf-8")
    got = wd.ProgressFiles([tmp_path]).runs()
    assert [r["_dir"] for r in got] == [str(tmp_path / "a")]
    assert wd.ProgressFiles([tmp_path / "missing"]).runs() == []


def test_a_real_evals_run_progress_file_is_read_and_paused_through_its_own_hook(tmp_path):
    """The reader and the pause action against evals/watch.py itself, not a copy of its format."""
    from evals import watch
    eye = watch.Watch(planned={"a": 10.0}, outdir=tmp_path / "run")
    (tmp_path / "run").mkdir()
    prog = watch.Progress(tmp_path / "run", eye, {"a": "llamacpp:a"}, total=5, done=0)
    prog.write()
    got = wd.ProgressFiles([tmp_path]).runs()
    assert len(got) == 1 and got[0]["total"] == 5 and got[0]["planned_s_per_case"] == {"a": 10.0}
    out = wd.Hands().do(wd.PAUSE, finding(progress=got[0]))
    assert "pause file written" in out
    with pytest.raises(watch.Stop):
        eye.before("a")


class Notifier(wd.Hands):
    def __init__(self):
        self.calls, fake = _osascript()
        super().__init__(run=fake, environ={}, platform="darwin")


def _fallbacks(*nodes):
    return [{"node": n, "requests": wd.FALLBACK_MAX, "aliases": []} for n in nodes]


def test_a_repeating_notify_is_shown_once_per_criterion_and_target_then_again_after_the_interval(tmp_path,
                                                                                               monkeypatch):
    monkeypatch.setattr(wd, "ESCALATE_AFTER", 99)
    conn = ms.connect()
    hand = Notifier()
    fake = Fake(tmp_path, fallbacks=_fallbacks("a", "b"))
    for i in range(3):
        wd.wake(conn, fake, hand, act=True, now=NIGHT + i * 300, say=lambda *_: None)
    assert [c[-2] for c in hand.calls] == ["node_fallbacks: node a", "node_fallbacks: node b"]
    outcomes = [r["outcome"] for r in _rows(conn)]
    assert sum(o.startswith("notified:") for o in outcomes) == 2
    assert sum(o.startswith("notify held") for o in outcomes) == 4
    wd.wake(conn, fake, hand, act=True, now=NIGHT + wd.NOTIFY_EVERY_S + 1, say=lambda *_: None)
    assert len(hand.calls) == 4


def test_a_failed_notify_does_not_hold_the_next_one(tmp_path, monkeypatch):
    monkeypatch.setattr(wd, "ESCALATE_AFTER", 99)
    conn = ms.connect()
    hand = Notifier()
    hand.run = _osascript(rc=1)[1]
    fake = Fake(tmp_path, fallbacks=_fallbacks("a"))
    wd.wake(conn, fake, hand, act=True, now=NIGHT, say=lambda *_: None)
    hand.run = _osascript()[1]
    wd.wake(conn, fake, hand, act=True, now=NIGHT + 300, say=lambda *_: None)
    assert [r["outcome"].split(":")[0] for r in _rows(conn)] == ["notify failed", "notified"]


def test_a_dry_run_records_the_notify_and_shows_nothing(tmp_path):
    conn = ms.connect()
    hand = Notifier()
    wd.wake(conn, Fake(tmp_path, fallbacks=_fallbacks("a")), hand, act=False, now=NIGHT, say=lambda *_: None)
    assert hand.calls == []
    assert [(r["action"], r["dry_run"], r["outcome"]) for r in _rows(conn)] == [("notify", 1, "dry-run")]
