"""A queued job runs the deploy's code, not whatever checkout queued it. #645."""
import json
import subprocess

import pytest

from harness import cli, paths, workqueue as wq


def _git(*args, cwd):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "-c", "init.defaultBranch=main", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def _repo(path, n):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=path)
    for i in range(n):
        _git("commit", "-q", "--allow-empty", "-m", f"c{i}", cwd=path)
    return _git("rev-parse", "HEAD", cwd=path)


@pytest.fixture
def deploy(tmp_path):
    d = (tmp_path / "deploy").resolve()
    _repo(d, 1)
    return d


@pytest.fixture
def stale(tmp_path):
    s = (tmp_path / "stale").resolve()
    _repo(s, 2)
    return s


def test_a_checkout_at_another_commit_is_refused_naming_both(deploy, stale):
    with pytest.raises(ValueError) as exc:
        wq.queue_cwd(stale, deploy)
    why = str(exc.value)
    for repo in (deploy, stale):
        assert _git("rev-parse", "HEAD", cwd=repo)[:8] in why
    assert "--cwd" in why


def test_a_checkout_at_the_deploy_commit_runs_in_the_deploy(tmp_path, deploy):
    same = (tmp_path / "same").resolve()
    _git("clone", "-q", str(deploy), str(same), cwd=tmp_path)
    assert wq.queue_cwd(same, deploy) == str(deploy)


def test_a_directory_outside_git_runs_in_the_deploy(tmp_path, deploy):
    plain = (tmp_path / "plain").resolve()
    plain.mkdir()
    assert wq.queue_cwd(plain, deploy) == str(deploy)


def test_inside_the_deploy_runs_where_it_was_asked(deploy):
    sub = deploy / "sub"
    sub.mkdir()
    assert wq.queue_cwd(sub, deploy) == str(sub)


def test_an_explicit_cwd_wins(deploy, stale):
    assert wq.queue_cwd(stale, deploy, explicit=str(stale)) == str(stale)


def test_no_deploy_keeps_the_callers_directory(stale):
    assert wq.queue_cwd(stale, None) == str(stale)


def test_the_cli_refuses_a_stale_checkout(monkeypatch, deploy, stale):
    monkeypatch.setattr(paths, "deploy_checkout", lambda: deploy)
    monkeypatch.chdir(stale)
    assert cli.main(["jobs", "add", "--", "true"]) == 1
    assert wq.jobs() == []


def test_the_cli_queues_in_the_deploy(monkeypatch, capsys, tmp_path, deploy):
    monkeypatch.setattr(paths, "deploy_checkout", lambda: deploy)
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert cli.main(["jobs", "add", "--json", "--", "true"]) == 0
    assert json.loads(capsys.readouterr().out)["job"]["cwd"] == str(deploy)


def test_the_cli_takes_an_explicit_cwd(monkeypatch, capsys, deploy, stale):
    monkeypatch.setattr(paths, "deploy_checkout", lambda: deploy)
    monkeypatch.chdir(stale)
    assert cli.main(["jobs", "add", "--cwd", str(stale), "--json", "--", "true"]) == 0
    assert json.loads(capsys.readouterr().out)["job"]["cwd"] == str(stale)


def test_a_bare_repo_for_a_typed_lane_names_the_spelling():
    from evals import run
    why = run.unrunnable("mlx-community/parakeet-tdt-0.6b-v2", "stt")
    assert "stt:mlx-community/parakeet-tdt-0.6b-v2" in why


def test_a_typed_candidate_gets_no_spelling_hint():
    from evals import run
    assert "stt:" not in run.unrunnable("stt:x/y", "stt").replace("stt:x/y", "")
