"""A queue that waits for a go, then works one job at a time. #353."""
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
    """A second `go` must not start a second runner on the same jobs."""
    held = wq._runner_lock()
    try:
        assert wq.running()
        assert wq.run_pending() == []
        assert wq.go(spawn=lambda *a, **k: pytest.fail("spawned twice")) is False
    finally:
        exclusive._release(held)
        os.close(held)
    assert not wq.running()


def test_go_starts_a_detached_runner():
    seen = {}
    assert wq.go(spawn=lambda argv, **kw: seen.update(argv=argv, kw=kw))
    assert seen["argv"][-2:] == ["-m", "harness.workqueue"]
    assert seen["kw"].get("start_new_session") or seen["kw"].get("creationflags")


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


def test_list_and_go_through_the_cli(capsys, monkeypatch):
    monkeypatch.setattr(wq, "go", lambda spawn=None: True)
    assert cli.main(["jobs", "go"]) == 1
    capsys.readouterr()
    cli.main(["jobs", "add", "--", "true"])
    capsys.readouterr()
    assert cli.main(["jobs", "go", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["pending"] == 1
    assert cli.main(["jobs", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["jobs"][0]["state"] == wq.PENDING
