"""#2015, #2017: a test fetches the candidate it is about to run and nothing keeps weights no test is about to use."""
from __future__ import annotations

import argparse
import subprocess

import pytest

from harness import disk, downloads, fetching, memory, reasons, screen, test_weights, workqueue
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from harness.commands import loop_steps
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from tests.test_harness_disk import DAY, NOW, inv, make_repo, world  # noqa: F401
from tests.test_harness_fetching_budget import _seed

GIB = fetching.GIB


def _entry(name, state="queued", group=disk.QUEUED, fetched_at=NOW - DAY, repo=None):
    return disk.Entry("hub", f"/hub/models--{name.replace('/', '--')}", name, repo or name, size=GIB, group=group,
                      fetched_at=fetched_at, waits=[(name, state)])


def _inv(*entries):
    return disk.Inventory("/hub", "/gguf", list(entries), [], [])


def _gone(*a, **k):
    return [e.name for e, _, _ in disk.due(*a, **k)]


# ---- what goes: weights no test is about to run --------------------------------------------------------------

def test_a_queued_or_screened_candidates_weights_go_stamped_once_no_test_is_about_to_run_them():
    got = disk.due(_inv(_entry("org/q"), _entry("org/s", "screened")), NOW)
    assert [(e.name, by) for e, _, by in got] == [("org/q", disk.TESTED), ("org/s", disk.TESTED)]


def test_a_screened_candidate_keeps_its_weights_only_while_the_measure_step_of_its_sweep_follows():
    i = _inv(_entry("org/q"), _entry("org/s", "screened"))
    assert _gone(i, NOW, keep_states=("screened",)) == ["org/q"]
    assert _gone(i, NOW) == ["org/q", "org/s"]


def test_one_tests_end_removes_its_own_candidate_and_no_other():
    i = _inv(_entry("org/a"), _entry("org/b"), _entry("org/base", repo="org/base"))
    i.entries[2].needed_by = ["org/a"]
    assert _gone(i, NOW, names=["Org/A"]) == ["org/a", "org/base"]


def test_a_name_kept_or_a_running_job_names_stays():
    i = _inv(_entry("org/a"), _entry("org/b"), _entry("org/c"))
    assert _gone(i, NOW, keep=["org/a"], words=["python -m evals.run --candidates org/b --screen"]) == ["org/c"]


def test_an_unfinished_download_kept_weights_and_unrecorded_ones_never_go():
    i = _inv(_entry("org/fetching", fetched_at=0), _entry("org/served", group=disk.KEEP),
             _entry("org/rejected", "declined", group=disk.REJECTED))
    stray = _entry("org/stray")
    stray.unrecorded = True
    i.entries.append(stray)
    assert _gone(i, NOW) == []


def test_unowned_weights_go_past_their_deadline_and_never_at_one_tests_end():
    old = _entry("org/old", group=disk.UNKNOWN, fetched_at=NOW - disk.UNOWNED_DEADLINE_S - 1)
    young = _entry("org/young", group=disk.UNKNOWN, fetched_at=NOW - disk.UNOWNED_DEADLINE_S + 60)
    got = disk.due(_inv(old, young), NOW)
    assert [(e.name, by) for e, _, by in got] == [("org/old", disk.UNOWNED)]
    assert _gone(_inv(old), NOW, names=["org/old"]) == []


def test_the_interactive_servers_pinned_stems_are_kept(monkeypatch):
    monkeypatch.setattr(disk, "_pinned", lambda: {"code": {"stem": "Ornith-1.5-35B-Q4_K_M"}})
    k = disk.keepers(None, gateway_files=[], typed={}, adopted={})
    assert k.stems["ornith-1.5-35b-q4_k_m"] == "pinned by the interactive server for code"


def test_a_running_job_names_its_argv_and_the_candidate_a_confirmation_runs(world, monkeypatch):
    _seed(world.conn, "org/held", 1.0)
    vid = world.conn.execute("SELECT state_verdict_id FROM proposals WHERE name = 'org/held'").fetchone()[0]
    monkeypatch.setattr(workqueue, "running_here", lambda conn=None: [
        {"argv": ["python", "-m", "harness.cli", "adopt", "--confirm", str(vid)]},
        {"argv": '["python", "-m", "evals.run", "--candidates", "Org/Other"]'}])
    got = disk.busy(world.conn)
    assert "org/held" in got and any("org/other" in w for w in got)


def test_the_first_sweep_removes_screened_waiting_weights_and_stamps_them_keeping_the_verdict(world):
    d = make_repo(world.hub, "org/waiting", size=4096)
    _seed(world.conn, "org/waiting", 1.0)
    ms.decide(world.conn, "org/waiting", "screened", tier="screen", detail="ran")
    world.conn.execute("UPDATE downloads SET finished_at = ? WHERE repo = 'org/waiting'", (NOW - 30 * DAY,))
    world.conn.commit()
    got = disk.clean(inv(world), NOW, world.conn)
    assert [r["repo"] for r in got["evicted"]] == ["org/waiting"] and not d.exists()
    row = world.conn.execute("SELECT state, removed_by FROM downloads WHERE repo = 'org/waiting'").fetchone()
    assert (row["state"], row["removed_by"]) == ("removed", disk.TESTED)
    assert ms.latest(world.conn, "org/waiting")["outcome"] == "screened"


def test_soh_disk_says_what_the_next_sweep_removes(world):
    make_repo(world.hub, "org/waiting", size=4096)
    _seed(world.conn, "org/waiting", 1.0)
    world.conn.execute("UPDATE downloads SET finished_at = ? WHERE repo = 'org/waiting'", (NOW - DAY,))
    world.conn.commit()
    i = inv(world)
    assert disk.summary(i, NOW)["next_sweep"] == {disk.TESTED: {"count": 1, "bytes": 4096}}
    assert f"the next sweep removes 1 more, 0.0 GiB: {disk.TESTED}" in disk.table(i, NOW)


# ---- the fetch a test does as it starts -----------------------------------------------------------------------

def test_a_measurement_whose_weights_were_removed_fetches_them_again(monkeypatch):
    conn = ms.connect()
    _seed(conn, "org/gone", 2.0)
    got = []
    monkeypatch.setattr(fetching, "download", lambda repo, **k: got.append((repo, k["require_weights"])) or "/x")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    assert fetching.ensure(conn, "org/gone", free=1000 * GIB, floor=0) == ""
    assert got == [("org/gone", True)]


def test_a_measurement_whose_weights_are_here_fetches_nothing(monkeypatch):
    conn = ms.connect()
    monkeypatch.setattr(fetching, "missing", lambda name, conn=None: [])
    monkeypatch.setattr(fetching, "download", lambda *a, **k: pytest.fail("fetched weights already here"))
    assert fetching.ensure(conn, "org/here") == ""


def test_a_measurement_refetch_below_the_floor_says_why_and_fetches_nothing(monkeypatch):
    conn = ms.connect()
    _seed(conn, "org/big", 50.0)
    monkeypatch.setattr(fetching, "download", lambda *a, **k: pytest.fail("fetched below the floor"))
    why = fetching.ensure(conn, "org/big", free=60 * GIB, floor=30 * GIB)
    assert why.startswith("org/big: ") and "floor" in why


class _Launched(Exception):
    pass


def _measure_until_launch(monkeypatch, missing):
    """_measure up to its launch with the fetch saying `missing`: (rc, sweep lines), or _Launched."""
    from harness import adopt, candidates, winners
    monkeypatch.setattr(test_weights, "fetched", lambda name: missing)
    monkeypatch.setattr(candidates, "for_proposal", lambda *a, **k: "org/c")
    monkeypatch.setattr(winners, "typed", lambda: {"code": "org/inc"})
    monkeypatch.setattr(adopt, "default_for", lambda lane, typed: typed)
    monkeypatch.setattr(measure_cmd, "_zero_pass", lambda *a: None)
    monkeypatch.setattr(measure_cmd, "_screen_refusal", lambda *a: "")
    monkeypatch.setattr(measure_cmd, "unserved", lambda spec: ("", ""))
    monkeypatch.setattr(measure_cmd, "_plan", lambda *a, **k: (None, object()))
    monkeypatch.setattr(measure_cmd, "_held", lambda *a: (None, None))
    monkeypatch.setattr(adopt, "undecidable", lambda *a: None)
    monkeypatch.setattr(screen, "routed_gateway", lambda spec: "")

    def launched(*a, **k):
        raise _Launched()
    monkeypatch.setattr(measure_cmd, "_slice", launched)
    sweep = type("S", (), {"lines": [], "remaining": lambda self: 3600})()
    rc = measure_cmd._measure(argparse.Namespace(lane="code", dry_run=False), {"name": "org/c", "lane": "code"},
                              [], sweep)
    return rc, sweep.lines


def test_measure_fetches_before_it_launches_and_a_failed_fetch_is_said_not_run(monkeypatch):
    assert _measure_until_launch(monkeypatch, "network down") == (
        0, ["org/c: not measured: its weights could not be fetched: network down"])
    with pytest.raises(_Launched):
        _measure_until_launch(monkeypatch, "")


def test_measure_removes_its_challengers_weights_when_the_run_ends_and_keeps_them_while_it_goes_on(monkeypatch):
    from evals import watch
    released = []
    monkeypatch.setattr(test_weights, "release", released.append)
    for got, want in ((0, ["org/c"]), (1, ["org/c"]), (watch.PAUSED, [])):
        released.clear()
        monkeypatch.setattr(measure_cmd, "_measure", lambda a, row, loaded, sweep=None, rc=got: rc)
        measure_cmd._measure_and_adopt(argparse.Namespace(dry_run=False), {"name": "org/c"})
        assert released == want, got
    monkeypatch.setattr(measure_cmd, "_measure", lambda a, row, loaded, sweep=None: 0)
    measure_cmd._measure_and_adopt(argparse.Namespace(dry_run=True), {"name": "org/c"})
    assert released == []


def test_an_unfetched_candidate_is_sized_from_its_listing(monkeypatch):
    conn = ms.connect()
    _seed(conn, "org/listed", 12.5)
    conn.close()
    assert memory.need_gb("org/listed") == pytest.approx(12.5)
    assert memory.need_gb("org/never-seen") is None


# ---- the screen: fetch at start, remove at the end -----------------------------------------------------------

class _Done:
    returncode = 0
    stderr = ""


def _screen(monkeypatch, outcome, *, fits=True, fetch_ok=True, limit=5):
    conn = ms.connect()
    _seed(conn, "org/new", 40.0)
    conn.close()
    plan = [{"name": "org/new", "lane": "code", "state": screen.WAITING, "candidate": "org/new", "modality": "code",
             "why_not": "weights are not on disk; the screen fetches them as it starts"}]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(screen, "plan", lambda rows, **k: [{**rows[0], "state": screen.READY}])
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, "") if fits else
                        (False, "needs 40.0 GB, only 9.0 GB is safely available"))
    monkeypatch.setattr(memory, "wait_for", lambda *a, **k: "room_gb:>40.0")
    fetched, released = [], []
    monkeypatch.setattr(fetching, "for_test", lambda conn, row, **k: fetched.append(row["name"]) or (
        {"repo": row["name"], "ok": True, "why": "/x"} if fetch_ok else
        {"repo": row["name"], "ok": False, "why": "its download would take 40.0 GiB under the floor"}))
    monkeypatch.setattr(screen_cmd, "_release", lambda store, r: released.append(r["name"]))
    monkeypatch.setattr(screen_cmd, "snapshot_gap", lambda r, conn: "")
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (argv[0] == "screen" and ran.append(argv[-1])) or _Done())
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {"summary": {"x": {"passed": 0}}})
    monkeypatch.setattr(screen, "outcome", lambda *a, **k: outcome)
    rc = screen_cmd._report_screen(argparse.Namespace(lane="", top=5, limit=limit, run=True, json=False))
    return rc, fetched, ran, released


def test_a_declined_screen_fetched_its_candidate_first_and_leaves_no_weights_behind(monkeypatch):
    rc, fetched, ran, released = _screen(monkeypatch, screen.decide_class(reasons.CONTENT_FAILED))
    assert (rc, fetched, ran, released) == (0, ["org/new"], ["org/new"], ["org/new"])


def test_a_screened_candidate_keeps_its_weights_for_the_measure_step(monkeypatch):
    passed = screen.Verdict("screened", "ran and emitted", reasons.CANDIDATE)
    rc, fetched, ran, released = _screen(monkeypatch, passed)
    assert (fetched, ran, released) == (["org/new"], ["org/new"], [])


def test_a_candidate_that_does_not_fit_memory_now_downloads_nothing_and_says_why(monkeypatch):
    rc, fetched, ran, _ = _screen(monkeypatch, None, fits=False)
    assert (fetched, ran) == ([], [])
    conn = ms.connect()
    v = conn.execute("SELECT p.state, v.tier, v.reason, v.detail FROM proposals p JOIN verdicts v "
                     "ON v.id = p.state_verdict_id WHERE p.name = 'org/new'").fetchone()
    assert (v["state"], v["tier"], v["reason"]) == ("queued", "screen", reasons.MEMORY)
    assert "needs 40.0 GB" in v["detail"]


def test_a_refused_fetch_runs_nothing_and_its_leftovers_go(monkeypatch):
    rc, fetched, ran, released = _screen(monkeypatch, None, fetch_ok=False)
    assert (fetched, ran, released) == (["org/new"], [], ["org/new"])


def test_with_no_screen_slot_free_nothing_is_downloaded(monkeypatch):
    rc, fetched, ran, _ = _screen(monkeypatch, None, limit=0)
    assert (rc, fetched, ran) == (0, [], [])


# ---- the sweep: no fetch step, each step's end keeps only what the next step runs ---------------------------

def test_the_sweep_has_no_fetch_step_and_a_queued_fetch_step_runs_the_screen():
    assert "fetch" not in loop_cmd.SPEND_STEPS and "fetch" not in loop_steps.NAMES
    assert loop_steps.RETIRED == {"fetch": "screen"} and "screen" in loop_steps.NAMES


def test_the_screen_step_keeps_screened_weights_and_the_measure_step_keeps_only_paused_runs(
        monkeypatch, _no_real_disk_sweep):
    monkeypatch.setattr(loop_cmd.discover_cmd, "cmd_discover", lambda a: 0)
    monkeypatch.setattr("harness.gguf.pending", lambda: False)
    loop_cmd._screen(argparse.Namespace(top=1), None, {"per_s": 0.0}, [])
    assert _no_real_disk_sweep[-1] == ((), {"keep_states": ("screened",)})
    monkeypatch.setattr(measure_cmd, "take_incumbents", lambda want: [])
    monkeypatch.setattr(loop_cmd, "measure_queue", lambda *a, **k: [{"name": "org/a"}, {"name": "org/b"}])

    def measured(a, fresh, sweep, failed, rc=0, paused=None, **k):
        paused.append("org/b")
        return rc
    monkeypatch.setattr(loop_cmd, "_measure_all", measured)
    loop_cmd._measure(argparse.Namespace(top=0, lane=""), None, [])
    assert _no_real_disk_sweep[-1] == ((), {"keep": ["org/b"]})


def test_a_confirmation_releases_the_proposal_its_verdict_names(monkeypatch):
    conn = ms.connect()
    _seed(conn, "org/held", 1.0)
    vid = conn.execute("SELECT state_verdict_id FROM proposals WHERE name = 'org/held'").fetchone()[0]
    conn.close()
    released = []
    monkeypatch.setattr(test_weights, "release", released.append)
    test_weights.release_verdict(vid)
    test_weights.release_verdict(vid + 999)
    assert released == ["org/held"]


def test_the_measure_step_lists_each_run_that_paused_to_go_on(monkeypatch):
    from evals import watch
    monkeypatch.setattr(loop_cmd, "_gated", lambda row, want: "")
    monkeypatch.setattr(loop_cmd, "_beat", lambda tier, **k: None)
    monkeypatch.setattr(loop_cmd.repo_gate, "args_for", lambda a, row: a)
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt",
                        lambda a, row, sweep=None: watch.PAUSED if row["name"] == "org/b" else 0)
    paused = []
    loop_cmd._measure_all(argparse.Namespace(lane=""), [{"name": "org/a", "lane": "code"}, {"name": "org/b", "lane": "code"}],
                          None, [], room=lambda r: (True, 1.0, ""), headroom=lambda: 1e6, refusal=lambda lane: "",
                          paused=paused)
    assert paused == ["org/b"]
