"""#2132: a gateway started before the store answers waits, then says so; the watchdog restarts it once the store is back."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import shells
from harness import gateway_degraded, monitor
from harness import watchdog as wd
from harness import watchdog_hands, watchdog_observe
from tests.test_watchdog import NIGHT, Fake, judged

REPO = Path(__file__).resolve().parent.parent

FAKE_UV = """#!{python}
import os, subprocess, sys
args = sys.argv[1:]
home = os.environ["LOCALHARNESS_HOME"]
if "harness.gateway_key" in args:
    print("sk-test")
elif "harness.gateway_degraded" in args:
    sys.exit(subprocess.call([{python!r}, "-m", "harness.gateway_degraded", *args[args.index("harness.gateway_degraded") + 1:]],
                             cwd={repo!r}))
elif "harness.gateway" in args:
    count = os.path.join(home, "builds")
    n = int(open(count).read()) if os.path.exists(count) else 0
    open(count, "w").write(str(n + 1))
    if n < int(os.environ["FAKE_FAILS"]):
        print("psycopg.OperationalError: connection refused", file=sys.stderr)
        sys.exit(1)
    print(args[-1].replace("config.yaml", "config.served.yaml"))
elif "litellm" in args:
    print("ARGS=" + " ".join(args))
"""


def _serve(tmp_path, fails: int, wait: int, mark_first: bool = False):
    if not shells.BASH or sys.platform == "win32":
        pytest.skip("needs a POSIX bash")
    bin_dir, home, hf = tmp_path / "bin", tmp_path / "home", tmp_path / "hf"
    for d in (bin_dir, home, hf):
        d.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV.format(python=sys.executable, repo=str(REPO)), encoding="utf-8")
    uv.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_FAILS": str(fails),
           "HF_ROOT": str(hf), "HF_HOME": str(hf), "HF_MIN_FREE_GB": "0", "ANTHROPIC_API_KEY": "x",
           "LOCALHARNESS_HOME": str(home), "GATEWAY_SERVED_WAIT_S": str(wait), "GATEWAY_SERVED_POLL_S": "1",
           "PYTHONUTF8": "1"}
    if mark_first:
        subprocess.run([sys.executable, "-m", "harness.gateway_degraded", "mark", "stale"], cwd=REPO, env=env, check=True,
                       capture_output=True)
    got = subprocess.run([shells.BASH, "scripts/serve-gateway.sh"], cwd=REPO, env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    return got, home, int((home / "builds").read_text(encoding="utf-8"))


def test_a_store_that_answers_late_still_gets_the_served_config(tmp_path):
    got, home, builds = _serve(tmp_path, fails=2, wait=30)
    assert got.returncode == 0, got.stderr
    assert "config.served.yaml" in got.stdout and "WAIT" in got.stderr and builds == 3
    assert not (home / gateway_degraded.FILE).exists()


def test_a_store_that_never_answers_is_waited_for_a_bounded_time_then_marked(tmp_path):
    got, home, builds = _serve(tmp_path, fails=99, wait=2)
    assert got.returncode == 0, got.stderr
    assert "--config gateway/config.yaml " in got.stdout and "config.served.yaml" not in got.stdout
    assert "WARN" in got.stderr and "until the watchdog restarts it" in got.stderr
    assert builds == 3
    assert "could not be built" in (home / gateway_degraded.FILE).read_text(encoding="utf-8")


def test_a_successful_start_removes_an_earlier_mark(tmp_path):
    got, home, _ = _serve(tmp_path, fails=0, wait=5, mark_first=True)
    assert got.returncode == 0, got.stderr
    assert not (home / gateway_degraded.FILE).exists()


def _stale_store(monkeypatch, up: bool):
    from harness import adopt

    def lane_defaults(*a, **k):
        if not up:
            raise RuntimeError("psycopg.OperationalError: connection refused")
        return {}
    monkeypatch.setattr(adopt, "lane_defaults", lane_defaults)


def test_the_probe_calls_a_marked_gateway_unbuildable_while_the_store_refuses(monkeypatch):
    gateway_degraded.mark("planted")
    _stale_store(monkeypatch, up=False)
    got = watchdog_observe.Probes().gateway_degraded()
    assert got["reason"] == "planted" and "connection refused" in got["unbuildable"]
    _stale_store(monkeypatch, up=True)
    assert "unbuildable" not in watchdog_observe.Probes().gateway_degraded()


def test_the_probe_reads_nothing_without_a_mark(monkeypatch):
    _stale_store(monkeypatch, up=True)
    assert watchdog_observe.Probes().gateway_degraded() is None


class Marked(Fake):
    def __init__(self, tmp_path, mark, **kw):
        super().__init__(tmp_path, gateway=True, **kw)
        self._mark = mark

    def gateway_degraded(self):
        return self._mark


def test_the_watchdog_restarts_a_degraded_gateway_once_the_store_can_build_the_served_config(tmp_path):
    _, found, _ = judged(Marked(tmp_path, {"at": 1.0, "reason": "store down at start"}))
    got = [f for f in found if f.criterion == "gateway_degraded"]
    assert [f.subject.detail for f in got] == [{"service": "gateway"}]
    assert wd.BY_ID["gateway_degraded"].action == wd.RESTART


def test_the_watchdog_leaves_a_gateway_alone_while_the_store_still_refuses_or_none_is_marked(tmp_path):
    for mark in ({"at": 1.0, "reason": "r", "unbuildable": "connection refused"}, None):
        _, found, _ = judged(Marked(tmp_path, mark))
        assert [f for f in found if f.criterion == "gateway_degraded"] == []


def test_a_marked_gateway_that_is_not_loaded_is_skipped_not_restarted(tmp_path):
    fake = Marked(tmp_path, {"at": 1.0, "reason": "r"})
    fake._gateway = None
    _, found, skipped = judged(fake)
    assert "gateway_degraded" in skipped and not [f for f in found if f.criterion == "gateway_degraded"]


def test_the_restart_goes_through_launchd_sh_restart_gateway(shown_live, tmp_path):
    calls = []

    def fake(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    _, found, _ = judged(Marked(tmp_path, {"at": 1.0, "reason": "r"}))
    f = next(f for f in found if f.criterion == "gateway_degraded")
    assert watchdog_hands.Hands(run=fake).do(wd.RESTART, f).startswith("restarted gateway")
    assert calls[0][-2:] == ["restart", "gateway"]


def test_monit_pages_a_degraded_gateway_and_says_when_it_recovers(tmp_path):
    from tests.test_monitor_1485 import _spec
    text = monitor.render(_spec(tmp_path))
    check = text.split("check program gateway_served", 1)[1].split("\n\n", 1)[0]
    assert "monit-gateway.sh" in check and 'monit-alert.sh gateway-degraded"' in check and "recovered" in check
    assert "gateway-degraded" in monitor.KINDS
    assert "gateway_served" not in monitor.render(_spec(tmp_path, services=[("mlx", 8081)]))


def test_the_monit_check_fails_only_while_a_mark_exists(capsys):
    assert gateway_degraded.check() == 0
    gateway_degraded.mark("store down at start")
    assert gateway_degraded.check() == 1
    assert "store down at start" in capsys.readouterr().out
    gateway_degraded.clear()
    assert gateway_degraded.check() == 0
