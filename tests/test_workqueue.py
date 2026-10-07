"""The shared work queue: any caller adds, one worker runs, the owner comes first. #353."""
import json
import os
import sys

import pytest

from harness import cli, exclusive, workqueue as wq


@pytest.fixture(autouse=True)
def _no_marker(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)


def py(code):
    return [sys.executable, "-c", code]


def test_adding_runs_nothing(tmp_path):
    """The whole point: line it up now, start it later."""
    flag = tmp_path / "ran"
    wq.add(py(f"open({str(flag)!r}, 'w')"), title="touch")
    assert [j["state"] for j in wq.jobs()] == [wq.PENDING]
    assert not flag.exists()


def test_jobs_run_in_the_order_they_were_added(tmp_path):
    out = tmp_path / "order"
    for n in ("a", "b", "c"):
        wq.add(py(f"open({str(out)!r}, 'a').write({n!r})"))
    got = wq.run_pending()
    assert out.read_text(encoding="utf-8") == "abc"
    assert [j["state"] for j in got] == [wq.DONE] * 3


def test_a_failed_job_is_recorded_and_the_rest_still_run(tmp_path):
    out = tmp_path / "after"
    wq.add(py("import sys; print('boom'); sys.exit(3)"), title="fails")
    wq.add(py(f"open({str(out)!r}, 'w')"), title="after")
    got = wq.run_pending()
    assert [(j["state"], j["rc"]) for j in got] == [(wq.FAILED, 3), (wq.DONE, 0)]
    assert "boom" in open(got[0]["log"], encoding="utf-8").read()
    assert out.exists()


def test_a_job_does_not_hold_the_machine_lock_for_its_whole_run(tmp_path):
    """#371: a queued discovery download blocked a GPU eval for its whole
    duration. Commands that load models take the lock themselves."""
    probe = ("import os, sys; sys.path.insert(0, %r); "
             "from harness import exclusive as e; "
             "fd = os.open(e.lock_path(), os.O_RDWR | os.O_CREAT); "
             "print('free' if e._take(fd) else 'held', os.environ.get(%r))"
             % (str(__import__('pathlib').Path(__file__).resolve().parents[1]),
                exclusive.HELD_ENV))
    wq.add(py(probe))
    job = wq.run_pending()[0]
    assert open(job["log"], encoding="utf-8").read().strip() == "free None"


def test_only_one_runner_works_the_queue():
    """Two workers must never run the same jobs."""
    held = wq._runner_lock()
    try:
        assert wq.running()
        wq.add(py("pass"))
        assert wq.run_pending() == []
    finally:
        exclusive._release(held)
        os.close(held)
    assert not wq.running()


from harness import pressure  # noqa: E402

CALM = pressure.Pressure(level=pressure.NORMAL)
BUSY = pressure.Pressure(level=pressure.WARN)
UNKNOWN = pressure.Pressure()


def test_pause_closes_the_gate_and_resume_opens_it():
    wq.pause()
    assert wq.gate(sample=lambda: CALM) == (False, "paused (soh jobs resume)")
    wq.resume()
    assert wq.gate(sample=lambda: CALM)[0]


def test_memory_pressure_closes_the_gate_and_says_so():
    ok, why = wq.gate(sample=lambda: BUSY)
    assert not ok and "memory pressure" in why


def test_unknown_pressure_does_not_block():
    assert wq.gate(sample=lambda: UNKNOWN)[0]


def test_the_worker_runs_nothing_under_memory_pressure(tmp_path):
    flag = tmp_path / "ran"
    wq.add(py(f"open({str(flag)!r}, 'w')"))
    wq.serve(gate_fn=lambda: wq.gate(sample=lambda: BUSY), forever=False)
    assert not flag.exists()
    assert wq.jobs()[0]["state"] == wq.PENDING


def test_the_worker_runs_the_queue_when_memory_is_calm(tmp_path):
    flag = tmp_path / "ran"
    wq.add(py(f"open({str(flag)!r}, 'w')"))
    wq.serve(gate_fn=lambda: wq.gate(sample=lambda: CALM), forever=False)
    assert flag.exists() and wq.jobs()[0]["state"] == wq.DONE


def test_a_closing_gate_stops_the_next_job_not_the_running_one(tmp_path):
    """The gate is checked between jobs: work in progress is never thrown away."""
    first, second = tmp_path / "1", tmp_path / "2"
    wq.add(py(f"open({str(first)!r}, 'w')"))
    wq.add(py(f"open({str(second)!r}, 'w')"))
    answers = iter([(True, "away"), (False, "back")])
    wq.run_pending(gate=lambda: next(answers, (False, "back")))
    assert first.exists() and not second.exists()
    assert [j["state"] for j in wq.jobs()] == [wq.DONE, wq.PENDING]


def test_a_job_cut_off_mid_run_is_not_silently_rerun(tmp_path):
    """A reboot leaves a job marked running. It may be half done."""
    job = wq.add(py("pass"))
    job["state"] = wq.RUNNING
    wq._write(job)
    wq.run_pending()
    got = wq.jobs()[0]
    assert got["state"] == wq.FAILED and "interrupted" in got["note"]


def test_only_a_pending_job_can_be_cancelled():
    job = wq.add(py("pass"))
    wq.run_pending()
    with pytest.raises(ValueError, match="only a pending job"):
        wq.cancel(job["id"])
    other = wq.add(py("pass"))
    wq.cancel(other["id"])
    assert [j["id"] for j in wq.jobs()] == [job["id"]]


def test_the_command_keeps_its_own_separators_and_flags(capsys):
    assert cli.main(["jobs", "add", "--title", "T", "--json", "--",
                     "echo", "--title", "x", "--", "y"]) == 0
    job = json.loads(capsys.readouterr().out)["job"]
    assert job["title"] == "T"
    assert job["argv"] == ["echo", "--title", "x", "--", "y"]


def test_pause_resume_and_list_through_the_cli(capsys):
    assert cli.main(["jobs", "pause", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is True
    cli.main(["jobs", "add", "--", "true"])
    capsys.readouterr()
    assert cli.main(["jobs", "list", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["jobs"][0]["state"] == wq.PENDING and got["gate_open"] is False
    assert cli.main(["jobs", "resume", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is False


def test_higher_priority_runs_first_and_ties_keep_their_order(tmp_path):
    """#361. An image someone is waiting for must not sit behind a night of
    benchmarks."""
    out = tmp_path / "order"
    for n, p in (("a", 0), ("b", 0), ("c", 5)):
        wq.add(py(f"open({str(out)!r}, 'a').write({n!r})"), priority=p)
    wq.run_pending()
    assert out.read_text(encoding="utf-8") == "cab"


def test_a_pending_job_can_be_reprioritised_and_a_finished_one_cannot(tmp_path):
    first = wq.add(py("pass"))
    second = wq.add(py("pass"))
    wq.set_priority(second["id"], 3)
    assert [j["id"] for j in wq.pending()] == [second["id"], first["id"]]
    wq.run_pending()
    with pytest.raises(ValueError, match="only a pending job"):
        wq.set_priority(first["id"], 9)


def test_priority_through_the_cli(capsys):
    cli.main(["jobs", "add", "--", "true"])
    cli.main(["jobs", "add", "--priority", "7", "--", "true"])
    capsys.readouterr()
    assert cli.main(["jobs", "priority", "0001", "9", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["job"]["priority"] == 9
    assert [j["id"] for j in wq.pending()] == ["0001", "0002"]
    assert cli.main(["jobs", "priority", "0001"]) == 1


@pytest.mark.parametrize("argv,why", [
    (["uv run python -m evals.run --repeat 3", "--modality", "code"], "one argument"),
    (["--priority", "5", "--title", "x", "--", "true"], "did not recognise"),
])
def test_a_command_that_cannot_run_is_refused_when_queued(argv, why):
    """#363: five overnight jobs failed rc=127 hours after queueing."""
    with pytest.raises(ValueError, match=why):
        wq.add(argv)
    assert wq.jobs() == []


def test_a_real_path_with_a_space_is_still_a_command(tmp_path):
    """Negative control."""
    exe = tmp_path / "my tool"
    exe.write_text("", encoding="utf-8")
    assert wq.add([str(exe)])["argv"] == [str(exe)]


ADDER = """
import sys
from harness import workqueue as wq
for _ in range(int(sys.argv[1])):
    print(wq.add(["true"], requested_by=sys.argv[2])["id"], flush=True)
"""


def test_concurrent_adds_from_two_processes_get_distinct_ids(tmp_path):
    """#418: ids were max+1 over the files with no lock, so MCP and CLI could collide."""
    import subprocess
    from harness import memory_store as ms
    ms.connect().close()
    script = tmp_path / "adder.py"
    script.write_text(ADDER, encoding="utf-8")
    procs = [subprocess.Popen([sys.executable, str(script), "15", who],
                              stdout=subprocess.PIPE, text=True)
             for who in ("mcp", "cli")]
    ids = [line for p in procs for line in p.communicate(timeout=120)[0].split()]
    assert all(p.returncode == 0 for p in procs)
    assert len(ids) == 30 and len(set(ids)) == 30
    assert sorted(j["id"] for j in wq.jobs()) == sorted(ids)
    assert {j["requested_by"] for j in wq.jobs()} == {"mcp", "cli"}


def test_a_cancelled_highest_id_is_not_handed_out_again():
    wq.add(py("pass"))
    top = wq.add(py("pass"))
    wq.cancel(top["id"])
    assert wq.get(top["id"]) is None
    assert wq.add(py("pass"))["id"] == f"{int(top['id']) + 1:04d}"


def test_a_job_is_a_row_in_the_store():
    from harness import memory_store as ms
    job = wq.add(["echo", "hi there"], title="t", priority=4, requested_by="cli")
    conn = ms.connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?",
                           (int(job["id"]),)).fetchone()
    finally:
        conn.close()
    assert json.loads(row["argv"]) == ["echo", "hi there"]
    assert (row["state"], row["priority"], row["requested_by"]) == (wq.PENDING, 4, "cli")
    assert row["machine_id"] is not None
    assert not (wq.root() / "jobs").exists()


def test_ids_are_ordered_as_numbers_not_filenames():
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        conn.execute("INSERT INTO jobs (id, argv, created_at) "
                     "VALUES (9999, '[\"true\"]', 0)")
        conn.commit()
    finally:
        conn.close()
    nxt = wq.add(py("pass"))
    assert nxt["id"] == "10000"
    assert [j["id"] for j in wq.pending()] == ["9999", "10000"]


def test_another_machines_job_is_not_run_here(tmp_path):
    """A shared store holds every machine's queue; a worker runs only its own."""
    from harness import memory_store as ms
    flag = tmp_path / "ran"
    job = wq.add(py(f"open({str(flag)!r}, 'w')"))
    conn = ms.connect()
    try:
        other = ms.remember_machine(conn, {"hw_model": "Other1,1", "os": "Linux",
                                           "arch": "x86_64"})
        conn.execute("UPDATE jobs SET machine_id = ? WHERE id = ?",
                     (other, int(job["id"])))
        conn.commit()
    finally:
        conn.close()
    assert wq.run_pending() == [] and not flag.exists()
    conn = ms.connect()
    try:
        conn.execute("UPDATE jobs SET machine_id = ? WHERE id = ?",
                     (ms.machine_row(conn), int(job["id"])))
        conn.commit()
    finally:
        conn.close()
    assert [j["state"] for j in wq.run_pending()] == [wq.DONE] and flag.exists()


STORE_A_RUN = """
import sys
from evals.run import store_run
row = {"case_id": "c1", "candidate": "local-mid", "passed": True, "seconds": 1.0,
       "peak_kb": 0, "detail": "", "output": None, "artifact_path": None, "warnings": [], "metrics": {}}
print(store_run(sys.argv[1], {"generated": "2026-10-06T12:00:00",
                              "environment": {}, "receipt": {"modality": "code"},
                              "specs": {}, "rows": [row]}, 0.0))
"""


def test_a_job_that_ran_evals_links_to_its_run(tmp_path):
    from pathlib import Path

    from harness import paths
    script = tmp_path / "store_run.py"
    script.write_text(STORE_A_RUN, encoding="utf-8")
    root = str(Path(__file__).resolve().parents[1])
    ran = wq.add([sys.executable, str(script), str(paths.runs() / "20261006-job")],
                 cwd=root)
    plain = wq.add(py("pass"))
    done = wq.run_pending()
    run_id = int(open(done[0]["log"], encoding="utf-8").read().split()[-1])
    assert wq.get(ran["id"])["runs"] == [run_id]
    assert wq.get(plain["id"])["runs"] == []


def test_a_run_stored_outside_any_job_links_to_none(monkeypatch, store_run):
    """Negative control: only a queued job's environment names a job."""
    from harness import memory_store as ms
    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    wq.add(py("pass"))
    run_id = store_run("20261006-alone", "code", {"local-mid": {"pass_rate": 1.0}})
    conn = ms.connect()
    try:
        assert not wq.link_run(conn, run_id)
        assert not wq.link_run(conn, run_id, {wq.JOB_ENV: "4242"})
        assert conn.execute("SELECT job_id FROM runs WHERE id = ?",
                            (run_id,)).fetchone()["job_id"] is None
    finally:
        conn.close()


def _old_job(home, n, **kw):
    d = home / "queue" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    job = {"id": f"{n:04d}", "title": f"job {n}", "kind": "command", "output": "",
           "priority": 0, "argv": ["true"], "cwd": "/", "state": "done",
           "added": "2026-10-05T01:00:00", "started": "2026-10-05T01:00:01",
           "finished": "2026-10-05T01:00:02", "rc": 0, "log": ""}
    job.update(kw)
    (d / f"{n:04d}.json").write_text(json.dumps(job), encoding="utf-8")
    return d / f"{n:04d}.json"


def test_the_migration_imports_old_job_files_once_and_links_their_runs(
        _home, store_run, tmp_path):
    from harness import memory_store as ms, paths
    run_id = store_run("20261005-0017", "code", {"local-mid": {"pass_rate": 1.0}})
    log = tmp_path / "0017.log"
    log.write_text(f"x\nartifacts + results.json in "
                   f"{paths.runs() / '20261005-0017'}\n", encoding="utf-8")
    conn = ms.connect()
    conn.execute("UPDATE meta SET value = '34' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    files = [_old_job(_home, 3, state="pending", priority=10, kind="image",
                      output="/x.png"),
             _old_job(_home, 17, log=str(log)),
             _old_job(_home, 18, state="failed", rc=127, note="interrupted")]
    (_home / "queue" / "jobs" / "bad.json").write_text("{", encoding="utf-8")
    ms.connect().close()
    got = {j["id"]: j for j in wq.jobs()}
    assert sorted(got) == ["0003", "0017", "0018"]
    assert got["0003"]["priority"] == 10 and got["0003"]["kind"] == "image"
    assert got["0003"]["output"] == "/x.png" and got["0003"]["state"] == wq.PENDING
    assert got["0017"]["runs"] == [run_id]
    assert got["0017"]["added"] == "2026-10-05T01:00:00"
    assert got["0018"]["rc"] == 127 and got["0018"]["note"] == "interrupted"
    assert all(f.exists() for f in files)
    assert wq.add(py("pass"))["id"] == "0019"
    conn = ms.connect()
    try:
        assert wq.import_json(conn)["imported"] == 0
    finally:
        conn.close()
    assert len(wq.jobs()) == 4


def test_quiesce_waits_for_the_running_job_and_reports_it_was_not_paused():
    """#577: install must not boot out the worker under a running job."""
    answers = iter([True, True, False])
    naps = []
    assert wq.quiesce(sleep=naps.append, is_running=lambda: next(answers)) is False
    assert len(naps) == 2 and wq.paused()


def test_quiesce_keeps_the_owners_pause():
    wq.pause()
    assert wq.quiesce(sleep=lambda _: None, is_running=lambda: False) is True
    assert wq.paused()
