"""Worker quiesce before an install: a deadline, an owner told when it passes, a named end state. #1762."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import exclusive, monitor, paths, quiesce as q, workqueue as wq

REPO = Path(__file__).resolve().parents[1]
posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock held across processes")

# A quiesce with a one-second deadline, run while a job holds the runner lock and never yields.
NEVER_YIELDS = """
import sys
from harness import quiesce as q
q.QUIESCE_TIMEOUT_S = float(sys.argv[1])
print(q.quiesce(wait=0.05))
"""


def _hold_runner_lock() -> int:
    wq.root().mkdir(parents=True, exist_ok=True)
    fd = os.open(wq.root() / "runner.lock", os.O_RDWR | os.O_CREAT, 0o644)
    assert exclusive._take(fd)
    return fd


def _alerts() -> list[dict]:
    p = monitor.alerts_path()
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


@posix
@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/quiesce.py:quiesce")
def test_a_job_that_never_yields_ends_the_quiesce_at_its_deadline_and_says_so():
    fd = _hold_runner_lock()
    try:
        got = subprocess.run([sys.executable, "-c", NEVER_YIELDS, "1"], cwd=REPO, capture_output=True, text=True,
                             env={**os.environ, paths.ENV_VAR: str(paths.home())}, timeout=90)
    except subprocess.TimeoutExpired:
        pytest.fail("quiesce was still waiting 90 s into a 1 s deadline: it has none")
    finally:
        exclusive._release(fd)
        os.close(fd)
    assert got.returncode != 0 and "NotQuiesced" in got.stderr, got.stderr[-800:]
    assert "waiting up to 1 s" in got.stderr, "it says what it waits for before it waits"
    assert not wq.paused(), "the queue is left as it was found: running"
    said = [a for a in _alerts() if a["event"] == q.NOT_QUIESCED]
    assert len(said) == 1 and said[0]["kind"] == "service" and said[0]["service"] == "queue"
    assert "queue_quiesce_timeout" in said[0]["description"] and "soh jobs cancel" in said[0]["description"]


def test_the_cli_names_its_end_state_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(q, "QUIESCE_TIMEOUT_S", 0.0)
    monkeypatch.setattr(wq, "running", lambda: True)
    assert q.cli() == q.NOT_QUIESCED_RC
    out = capsys.readouterr()
    assert out.out.strip() == q.NOT_QUIESCED and out.err.startswith(f"{q.NOT_QUIESCED}: ")
    assert not wq.paused()


def test_the_cli_reports_the_prior_pause_when_nothing_runs(monkeypatch, capsys):
    monkeypatch.setattr(wq, "running", lambda: False)
    assert q.cli() == 0 and capsys.readouterr().out.strip() == "was-running"
    assert wq.paused()


@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/quiesce.py:quiesce")
def test_the_wait_never_sleeps_past_its_deadline_and_says_it_waits_once(capsys):
    t = [100.0]
    naps = []

    def nap(s):
        naps.append(s)
        t[0] += s

    with pytest.raises(q.NotQuiesced):
        q.quiesce(wait=0.4, sleep=nap, is_running=lambda: True, timeout=1.0, clock=lambda: t[0])
    assert t[0] == pytest.approx(101.0) and all(s > 0 for s in naps)
    assert capsys.readouterr().err.count("waiting up to 1 s") == 1


def test_an_owners_pause_outlives_an_expired_quiesce():
    wq.pause("owner")
    with pytest.raises(q.NotQuiesced):
        q.quiesce(sleep=lambda _: None, is_running=lambda: True, timeout=0.0)
    assert wq.paused()


def test_a_pause_taken_since_the_quiesce_paused_is_not_lifted_by_it():
    def again(_):
        wq.pause("owner, while the install waited")

    with pytest.raises(q.NotQuiesced):
        q.quiesce(sleep=again, is_running=lambda: True, timeout=0.5, wait=1.0)
    assert wq.paused()


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/quiesce.py:_read:except")
def test_an_owner_resume_during_the_wait_leaves_the_queue_running():
    def resumed(_):
        wq.resume()

    with pytest.raises(q.NotQuiesced):
        q.quiesce(sleep=resumed, is_running=lambda: True, timeout=0.5, wait=1.0)
    assert not wq.paused()


def test_the_install_does_not_reload_the_worker_under_a_job_that_outlived_the_quiesce():
    gen = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    body = gen.split("install_units() {", 1)[1].split("\n}\n", 1)[0]
    branch = body.split('[ "$was" = not-quiesced ]', 1)
    assert len(branch) == 2, "install reads the quiesce's named end state"
    taken = branch[1].split("fi", 1)[0]
    assert 'failed="$failed worker"' in taken and "continue" in taken, (
        "the worker is reported not loaded, and skipped rather than reloaded under its job")


def test_a_volume_stop_under_a_job_that_outlived_the_quiesce_stops_nothing(tmp_path, monkeypatch):
    from harness import volume
    monkeypatch.setattr(volume, "state_path", lambda: tmp_path / "volume.json")
    ran = []

    def expired():
        raise q.NotQuiesced("not-quiesced: job 0001 still running after 1800 s")

    ops = volume.Ops(run=lambda argv, **kw: ran.append(argv), quiesce=expired)
    with pytest.raises(volume.VolumeError, match="still running"):
        volume.stop("VOLUME", ops)
    assert ran == [] and not (tmp_path / "volume.json").exists()


def test_the_deploy_record_carries_the_not_quiesced_line(tmp_path):
    from harness import deploy_switch
    log = open(tmp_path / "deploy.log", "w+", encoding="utf-8")
    start = deploy_switch._size(log)
    log.write("waiting up to 1800 s\nnot-quiesced: job 0001 (confirm) still running after 1800 s; re-run\n")
    rec: dict = {}
    why = deploy_switch._audited(rec, log, start, "install exited rc 1")
    log.close()
    assert why.startswith("install exited rc 1: not-quiesced: job 0001"), why
