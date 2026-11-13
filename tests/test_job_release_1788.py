"""A job queued by one release and started after a deploy runs on the linked release, or is refused by name. #1788."""
import shutil

import pytest

from harness import cli, job_release, paths
from harness import job_state as js
from harness import memory_store as ms
from harness import workqueue as wq


def release(name, version=None):
    top = paths.home() / "releases" / name
    (top / "harness" / "memory_store").mkdir(parents=True)
    (top / "harness" / "memory_store" / "schema.py").write_text(
        f"SCHEMA_VERSION = {ms.SCHEMA_VERSION if version is None else version}\n", encoding="utf-8")
    (top / ".venv" / "bin").mkdir(parents=True)
    (top / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    (top / "pyproject.toml").write_text("", encoding="utf-8")
    return top.resolve()


@pytest.fixture
def two(monkeypatch):
    old, new = release("19-aaaaaaaaaaaa"), release("20-bbbbbbbbbbbb")
    monkeypatch.setattr(job_release, "here", lambda: new)
    return old, new


def queue(old, *words):
    return wq.add([str(old / ".venv" / "bin" / "python"), "-m", "harness.cli", *(words or ("jobs", "list"))],
                  cwd=str(old))


def migrate_past(old):
    (old / "harness" / "memory_store" / "schema.py").write_text(
        f"SCHEMA_VERSION = {ms.SCHEMA_VERSION - 1}\n", encoding="utf-8")


def run(job):
    ran = []
    got = wq.run_one(job, popen=lambda argv, **k: ran.append((list(argv), k["cwd"])) or type("P", (), {"returncode": 0}))
    return got, ran


def test_a_job_queued_before_a_migrating_deploy_runs_on_the_new_release_with_its_interpreter(two):
    old, new = two
    job = queue(old)
    migrate_past(old)
    got, ran = run(job)
    assert ran == [([str(new / ".venv" / "bin" / "python"), "-m", "harness.cli", "jobs", "list"], str(new))]
    assert got["state"] == wq.DONE
    row = wq.get(job["id"])
    assert row["cwd"] == str(new) and "19-aaaaaaaaaaaa" in row["note"] and "20-bbbbbbbbbbbb" in row["note"]


def test_a_job_whose_release_was_pruned_runs_on_the_new_release(two):
    old, new = two
    job = queue(old)
    shutil.rmtree(old)
    got, ran = run(job)
    assert [cwd for _, cwd in ran] == [str(new)] and got["state"] == wq.DONE
    assert "is gone" in wq.get(job["id"])["note"]


def test_a_never_started_job_on_a_still_readable_old_release_runs_new_code(two):
    old, new = two
    job = queue(old)
    _, ran = run(job)
    assert [cwd for _, cwd in ran] == [str(new)]


def test_a_command_the_new_release_refuses_fails_by_name_without_running(two):
    old, new = two
    job = queue(old, "no-such-verb-1788")
    migrate_past(old)
    got, ran = run(job)
    assert ran == []
    assert got["state"] == wq.FAILED and got["reason"] == js.RELEASE_REFUSED
    assert "19-aaaaaaaaaaaa" in got["note"] and "no-such-verb-1788" in got["note"]
    assert "no-such-verb-1788" in open(got["log"], encoding="utf-8").read()
    assert got["cwd"] == str(old)


def repended(job, why=js.DEPLOY_PAUSE):
    with wq._store() as c:
        assert js.move(c, job["id"], wq.PENDING, wq.RUNNING, js.CLAIMED)
        assert js.move(c, job["id"], wq.RUNNING, wq.PENDING, why, "paused for a deploy")
        c.commit()
    return wq.get(job["id"])


def test_a_started_step_resumes_in_its_own_release_while_that_release_can_run_it(two):
    old, _ = two
    job = repended(queue(old))
    _, ran = run(job)
    assert [cwd for _, cwd in ran] == [str(old)]


@pytest.mark.parametrize("how", ["migrated", "pruned"])
def test_a_started_step_whose_release_cannot_run_it_moves_to_the_new_release(two, how):
    old, new = two
    job = repended(queue(old))
    migrate_past(old) if how == "migrated" else shutil.rmtree(old)
    got, ran = run(job)
    assert [cwd for _, cwd in ran] == [str(new)] and got["state"] == wq.DONE


def test_a_job_outside_the_releases_runs_where_it_was_queued(two, tmp_path):
    job = wq.add(["true"], cwd=str(tmp_path))
    _, ran = run(job)
    assert ran == [(["true"], str(tmp_path))]


def test_a_worker_outside_the_releases_moves_nothing(two, monkeypatch):
    old, _ = two
    monkeypatch.setattr(job_release, "here", lambda: None)
    _, ran = run(queue(old))
    assert [cwd for _, cwd in ran] == [str(old)]


def test_paths_inside_the_old_release_map_to_the_same_place_in_the_new(two):
    old, new = two
    got = job_release.moved([f"{old}/.venv/bin/python", "-m", "x", f"{old}x", "/elsewhere", f"{old}/a/b"], old, new)
    assert got == [f"{new}/.venv/bin/python", "-m", "x", f"{old}x", "/elsewhere", f"{new}/a/b"]
    assert job_release.release_of(old / "evals") == old and job_release.release_of(paths.home()) is None


def test_the_new_release_checks_evals_run_and_soh_arguments_and_its_own_files(two):
    _, new = two
    py = str(new / ".venv" / "bin" / "python")
    assert job_release.refusal([py, "-m", "evals.run", "--no-such-flag-1788"], new)
    assert job_release.refusal([py, "-m", "evals.run", "--modality", "code"], new) == ""
    assert job_release.refusal(["uv", "run", "soh", "jobs", "list"], new) == ""
    assert "not in release" in job_release.refusal([str(new / "scripts" / "gone.sh")], new)


def test_soh_jobs_names_the_release_that_built_each_pending_job(two, monkeypatch, capsys):
    old, new = two
    monkeypatch.setattr(job_release, "target", lambda: new)
    moving, refused = queue(old), queue(old, "no-such-verb-1788")
    stays = repended(queue(old, "jobs", "list", "--json"))
    assert cli.main(["jobs", "list"]) == 0
    shown = capsys.readouterr()
    err = shown.out + shown.err
    line = {j: next(ln for ln in err.splitlines() if ln.strip().startswith(j)) for j in
            (moving["id"], refused["id"], stays["id"])}
    assert "[release 19-aaaaaaaaaaaa; starts on 20-bbbbbbbbbbbb]" in line[moving["id"]]
    assert "refused at start" in line[refused["id"]] and "no-such-verb-1788" in line[refused["id"]]
    assert "[release 19-aaaaaaaaaaaa, where it resumes]" in line[stays["id"]]


def test_morning_counts_jobs_built_by_another_release_and_those_refused(two):
    old, new = two
    queue(old)
    gone = queue(old, "no-such-verb-1788")
    migrate_past(old)
    run(gone)
    with wq._store() as c:
        r = job_release.morning(c, 0.0, where=new)
    assert [p["action"] for p in r["pending"]] == [job_release.MOVES]
    assert [x["job"] for x in r["refused"]] == [gone["id"]]
    lines = job_release.morning_lines(r)
    assert lines[0].startswith("releases  1 pending job(s) built by another release; 1 refused at start")
    assert any("no-such-verb-1788" in ln for ln in lines)


def test_the_morning_report_carries_the_release_lines(two):
    from harness import morning
    from harness.commands import morning as morning_cmd
    from tests import test_morning_867 as m867
    old, new = two
    queue(old)
    gone = queue(old, "no-such-verb-1788")
    run(gone)
    conn = ms.connect()
    try:
        r = morning.gather(conn, m867.NOW, m867.SINCE, gh=m867._gh(), git=m867._git(),
                           where=new, lanes=lambda c: [])
    finally:
        conn.close()
    assert [p["built"] for p in r["releases"]["pending"]] == ["19-aaaaaaaaaaaa"]
    assert any(ln.startswith("releases  1 pending job(s)") for ln in morning_cmd.render(r))
    assert any(n.startswith(f"job {gone['id']} was refused at start") and "no-such-verb-1788" in n for n in r["needs"])


def test_a_checkout_ahead_of_the_live_store_is_refused_and_a_scratch_one_queues(tmp_path, monkeypatch):
    top = tmp_path / "ahead"
    (top / "harness" / "memory_store").mkdir(parents=True)
    (top / "harness" / "memory_store" / "schema.py").write_text(
        f"SCHEMA_VERSION = {ms.SCHEMA_VERSION + 1}\n", encoding="utf-8")
    with wq._store() as c:
        assert wq.stale_schema(top, c) == ""
        monkeypatch.setattr(paths, "is_live", lambda p: True)
        why = wq.stale_schema(top, c)
    assert f"schema {ms.SCHEMA_VERSION + 1}" in why and "ahead" in why


def claimed(job):
    with wq._store() as c:
        assert js.move(c, job["id"], wq.PENDING, wq.RUNNING, js.CLAIMED)
        c.commit()
    return {**job, "state": wq.RUNNING}


@pytest.mark.parametrize("verb", ["jobs", "no-such-verb-1788"])
def test_a_log_write_that_dies_after_the_row_leaves_the_row_saying_it_all(two, tmp_path, verb):
    old, new = two
    job = claimed(queue(old, verb, *(["list"] if verb == "jobs" else [])))
    with wq._store() as c, pytest.raises(OSError):
        job_release.start(c, job, tmp_path / "no-such-dir" / "job.log", "")
    row = wq.get(job["id"])
    if verb == "jobs":
        assert row["cwd"] == str(new) and row["state"] == wq.RUNNING
        assert "19-aaaaaaaaaaaa" in row["note"] and job_release.plan(row, new) is None
    else:
        assert row["state"] == wq.FAILED and row["reason"] == js.RELEASE_REFUSED
        assert "no-such-verb-1788" in row["note"]


def test_a_working_directory_the_new_release_lacks_is_refused(two):
    old, new = two
    (old / "evals").mkdir()
    job = wq.add([str(old / ".venv" / "bin" / "python"), "-m", "harness.cli", "jobs", "list"], cwd=str(old / "evals"))
    shutil.rmtree(old)
    got, ran = run(job)
    assert ran == [] and got["reason"] == js.RELEASE_REFUSED and f"{new / 'evals'} is not in release" in got["note"]
