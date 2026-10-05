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


def test_each_job_holds_the_machine_lock_and_children_know_it(tmp_path):
    wq.add(py(f"import os; print(os.environ.get({exclusive.HELD_ENV!r}))"))
    job = wq.run_pending()[0]
    assert open(job["log"], encoding="utf-8").read().strip() == "1"


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


def AWAY():
    return True, "idle 30 min"


def HERE():
    return False, "in use"


def test_pause_closes_the_gate_and_resume_opens_it():
    wq.pause()
    assert wq.gate(away=AWAY) == (False, "paused (lh jobs resume)")
    wq.resume()
    assert wq.gate(away=AWAY)[0]


def test_the_owner_at_the_machine_closes_the_gate():
    assert not wq.gate(away=HERE)[0]
    assert "owner present" in wq.gate(away=HERE)[1]


def test_the_worker_runs_nothing_while_the_owner_is_here(tmp_path):
    flag = tmp_path / "ran"
    wq.add(py(f"open({str(flag)!r}, 'w')"))
    wq.serve(gate_fn=lambda: wq.gate(away=HERE), forever=False)
    assert not flag.exists()
    assert wq.jobs()[0]["state"] == wq.PENDING


def test_the_worker_runs_the_queue_when_the_owner_leaves(tmp_path):
    flag = tmp_path / "ran"
    wq.add(py(f"open({str(flag)!r}, 'w')"))
    wq.serve(gate_fn=lambda: wq.gate(away=AWAY), forever=False)
    assert flag.exists() and wq.jobs()[0]["state"] == wq.DONE


def test_a_returning_owner_stops_the_next_job_not_the_running_one(tmp_path):
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
