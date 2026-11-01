"""Machine monitoring through monit (#1485): the rendered config, the alert action, the webhook and the morning brief."""
from __future__ import annotations

import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from harness import knobs, monitor, morning, paths, workqueue
from harness.loopback import ThreadingHTTPServer
from harness.commands import morning as morning_cmd
from tests import shells
from tests.test_morning_867 import NOW, SINCE, _git, _gh, _report, _store

REPO = Path(__file__).resolve().parents[1]
SECRET = "tok3n-s3cret-0123456789abcdef"


def _spec(tmp_path, **kw):
    home = tmp_path / "lhhome"
    s = {"home": str(home), "scripts": str(REPO / "scripts"), "path": "/usr/bin:/bin", "data": "/data-volume",
         "models": "/models-volume", "models_floor_gib": 50, "services": [("gateway", 4000), ("mlx", 8081)]}
    s.update(kw)
    return s


@pytest.mark.skipif(shutil.which("monit") is None, reason="monit is not installed")
def test_the_rendered_config_passes_monit_t(tmp_path):
    s = _spec(tmp_path, data="/", models=str(tmp_path / "Volumes" / "Weights"))
    rc = monitor.write_rc(monitor.render(s), Path(s["home"]))
    assert oct(rc.stat().st_mode & 0o777) == "0o600"
    assert monitor.syntax(shutil.which("monit"), rc) == ""


def test_the_template_holds_no_name_from_this_machine(tmp_path):
    text = monitor.render(_spec(tmp_path))
    rest = text.replace(str(tmp_path), "").replace(str(REPO), "")
    for local in {getpass.getuser(), socket.gethostname().split(".")[0], str(Path.home())} - {""}:
        assert local not in rest
    assert "/Volumes/" not in rest and "://" not in rest and monitor.WEBHOOK not in text


def test_disk_floors_come_from_their_knobs_and_only_the_alert_recovers(tmp_path, monkeypatch):
    for name, unit, value in (("monitor_disk_alert", "GiB", 50), ("monitor_disk_pause", "GiB", 25),
                              ("monitor_memory_warn", "s", 600), ("monitor_cycle", "s", 300),
                              ("monitor_du_timeout", "s", 30), ("monitor_service_down", "s", 600)):
        k = knobs.KNOBS[name]
        assert (k.unit, k.default()) == (unit, value) and value in k.values
        assert "#1485" in k.note or "KB " in k.note or "owner" in k.note
    monkeypatch.setattr(monitor, "DISK_ALERT_GIB", 70)
    lines = monitor.render(_spec(tmp_path)).splitlines()
    alert = next(ln for ln in lines if "space free < 70 GB" in ln)
    pause = next(ln for ln in lines if "space free < 25 GB" in ln)
    assert "monit-alert.sh disk\"" in alert
    assert "recovered" in alert and "monit-alert.sh disk-pause\"" in pause and "recovered" not in pause


def test_memory_alerts_after_its_seconds_in_cycles(tmp_path, monkeypatch):
    assert "if status != 0 for 2 cycles" in monitor.render(_spec(tmp_path))
    monkeypatch.setattr(monitor, "MEMORY_WARN_S", 900)
    assert "if status != 0 for 3 cycles" in monitor.render(_spec(tmp_path))


def test_the_models_volume_alerts_when_unmounted_and_only_when_it_is_its_own(tmp_path):
    text = monitor.render(_spec(tmp_path))
    assert "check filesystem models_volume with path /models-volume" in text
    assert "if does not exist then exec" in text and "monit-alert.sh volume\"" in text
    assert "check filesystem models_volume" not in monitor.render(_spec(tmp_path, models=None))


def test_services_are_watched_by_port_and_alert_only(tmp_path):
    text = monitor.render(_spec(tmp_path))
    assert "check host service_gateway" in text and "failed port 4000 type tcp for 2 cycles" in text
    assert "restart" not in text and "stop" not in text


def test_a_path_monit_cannot_quote_is_refused(tmp_path):
    with pytest.raises(ValueError, match="space or a quote"):
        monitor.render(_spec(tmp_path, scripts="/a dir/scripts"))


def test_the_data_volume_is_the_mount_point_df_names_even_for_a_home_not_made_yet(tmp_path):
    seen = []

    def run(argv, **kw):
        seen.append(argv[-1])
        return subprocess.CompletedProcess(argv, 0, "Filesystem 512-blocks Used Available Capacity Mounted on\n"
                                                    "/dev/x 100 50 50 50% /mnt/data vol\n", "")
    assert monitor.mount_point(str(tmp_path / "not" / "yet"), run=run) == "/mnt/data vol"
    assert seen == [str(tmp_path)]


def test_services_are_the_installed_launchd_units(tmp_path, monkeypatch):
    (tmp_path / "com.unxmaal.localharness.gateway.plist").write_text("x", encoding="utf-8")
    monkeypatch.setenv("GATEWAY_PORT", "4100")
    assert monitor.watched_services(tmp_path) == [("gateway", 4100)]


class _Hook(BaseHTTPRequestHandler):
    bodies: list = []
    paths: list = []
    code = 204

    def do_POST(self):  # noqa: N802
        type(self).paths.append(self.path)
        type(self).bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(type(self).code)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def hook():
    _Hook.bodies, _Hook.paths, _Hook.code = [], [], 204
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Hook)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/api/webhooks/42/{SECRET}"
    srv.shutdown()


def _env_file(url):
    p = monitor.env_path()
    p.write_text(f"# owner's file\nexport {monitor.WEBHOOK}=\"{url}\"\n", encoding="utf-8")
    p.chmod(0o600)


def _monit_env(service="system_data", desc="space free 24.0 GB matches resource limit [space free < 25.0 GB]"):
    return {"MONIT_SERVICE": service, "MONIT_EVENT": "Resource limit matched", "MONIT_DESCRIPTION": desc}


def _running_eval(home: Path) -> Path:
    run = home / "runs" / "20261101-adopt"
    run.mkdir(parents=True)
    (run / "progress.json").write_text(json.dumps({"state": "running", "pid": os.getpid()}), encoding="utf-8")
    return run


@pytest.mark.skipif(sys.platform == "win32", reason="monit and its alert script are POSIX")
def test_the_alert_script_on_a_disk_pause_pauses_records_notifies_posts_and_runs_du(tmp_path, hook):
    home = paths.home()
    _env_file(hook)
    run = _running_eval(home)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "notifier.args"
    (bin_ / "terminal-notifier").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{calls}"\n', encoding="utf-8")
    (bin_ / "terminal-notifier").chmod(0o755)
    env = {**os.environ, **_monit_env(), "PATH": f"{bin_}:{os.environ['PATH']}"}
    got = subprocess.run([shells.resolve("bash"), str(REPO / "scripts" / "monit-alert.sh"), "disk-pause"], env=env, cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stdout + got.stderr
    assert workqueue.paused()
    assert (run / "pause").read_text(encoding="utf-8").endswith("monit: system_data space free 24.0 GB matches "
                                                                "resource limit [space free < 25.0 GB]")
    lines = [json.loads(ln) for ln in monitor.alerts_path().read_text(encoding="utf-8").splitlines()]
    assert [x["kind"] for x in lines] == ["disk-pause", "du"]
    assert "paused the job queue and 1 running eval(s)" in lines[0]["message"]
    assert lines[0]["webhook"] == "posted: HTTP 204" and lines[1]["description"].startswith("growers: ")
    posted = [json.loads(b) for b in _Hook.bodies]
    assert [list(p) for p in posted] == [["content"], ["content"]]
    assert posted[0]["content"] == f"{monitor.TITLE}: {lines[0]['message']}"
    assert posted[1]["content"].startswith(f"{monitor.TITLE}: system_data: growers: runs ")
    if sys.platform == "darwin":
        assert "SoHoT monit" in calls.read_text(encoding="utf-8")
    log = (home / "logs" / "monit-alert.log").read_text(encoding="utf-8")
    for where in (log, monitor.alerts_path().read_text(encoding="utf-8"), got.stdout, got.stderr):
        assert SECRET not in where and "/api/webhooks" not in where


def test_the_url_is_never_in_the_line_even_when_the_post_fails_or_monit_quotes_it(tmp_path, hook):
    _Hook.code = 404
    _env_file(hook)
    got = monitor.alert("service", _monit_env("service_gateway", f"failed {hook}"), notify=lambda t, m: m,
                        measure=lambda: [])
    assert got["webhook"] == "post failed: HTTP 404"
    _env_file(f"http://127.0.0.1:9/{SECRET}")
    got = monitor.alert("service", _monit_env("service_gateway"), notify=lambda t, m: "notified", measure=lambda: [])
    assert got["webhook"].startswith("post failed: ") and SECRET not in got["webhook"]
    assert monitor.post("x", f"discord/{SECRET}") == "post failed: ValueError"
    assert SECRET not in monitor.alerts_path().read_text(encoding="utf-8")


def test_a_disk_alert_does_not_pause_and_only_the_pause_threshold_does(tmp_path):
    paused = []
    for kind in ("disk", "memory", "volume", "disk-pause"):
        monitor.alert(kind, _monit_env(), notify=lambda t, m: "notified", send=lambda t, u: "posted",
                      pause=lambda why: paused.append(why) or {"queue": "paused", "runs": []}, measure=lambda: [])
    assert len(paused) == 1 and paused[0].startswith("monit: system_data")


def test_du_runs_only_on_a_disk_alert(tmp_path):
    measured = []
    for kind in ("memory", "service", "volume", "volume-low", "recovered", "disk", "disk-pause"):
        monitor.alert(kind, _monit_env(), notify=lambda t, m: "", send=lambda t, u: "", pause=lambda why: {},
                      measure=lambda: measured.append(1) or [])
    assert len(measured) == 2


def test_with_no_webhook_nothing_posts_and_the_line_says_so(tmp_path):
    sent = []
    got = monitor.alert("memory", _monit_env("memory_pressure", "level 2"), notify=lambda t, m: "notified",
                        send=lambda t, u: sent.append(u) or "posted")
    assert sent == [] and got["webhook"] == "no webhook set"
    probs = monitor.status(which=lambda n: "/x/monit", expected="")["problems"]
    assert any(p.startswith(f"no {monitor.WEBHOOK}") and "desktop and the morning brief only" in p for p in probs)


def test_the_bounded_du_stops_at_its_timeout_and_says_not_measured(tmp_path):
    (tmp_path / "slow").mkdir()
    (tmp_path / "fast").mkdir()

    def popen(argv, **kw):
        if argv[-1].endswith("slow"):
            return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], **kw)
        return subprocess.Popen([sys.executable, "-c", "print('2048\\tx')"], **kw)
    rows = monitor.du([("slow", tmp_path / "slow"), ("fast", tmp_path / "fast"), ("gone", tmp_path / "gone")],
                      timeout=0.5, popen=popen)
    by = {r["name"]: r for r in rows}
    assert by["slow"]["kib"] is None and by["slow"]["why"] == "over 0.5s, not measured"
    assert by["fast"]["kib"] == 2048 and by["gone"]["why"] == "absent"
    assert monitor.du_line(rows).startswith("growers: fast 0.0 GiB, ")


def test_the_desktop_notice_uses_terminal_notifier_when_installed(tmp_path):
    seen = []
    out = monitor.desktop("t", "m", run=lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0),
                          which=lambda n: "/x/terminal-notifier", platform="darwin")
    assert out == "notified" and seen[0][:5] == ["/x/terminal-notifier", "-title", "t", "-message", "m"]
    out = monitor.desktop("t", "m", run=lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0),
                          which=lambda n: None, platform="darwin")
    assert seen[1][0] == "osascript"


def test_the_morning_brief_shows_the_monit_summary_and_open_alerts(tmp_path):
    monitor.record({"at": SINCE - 60, "kind": "memory", "service": "memory_pressure", "description": "old"})
    monitor.record({"at": NOW - 7200, "kind": "disk", "service": "system_data", "description": "space free 40 GB"})
    monitor.record({"at": NOW - 7100, "kind": "du", "service": "system_data", "description": "growers: runs 9 GiB"})
    monitor.record({"at": NOW - 3600, "kind": "service", "service": "service_tts", "description": "port 8890"})
    monitor.record({"at": NOW - 1800, "kind": "recovered", "service": "service_tts", "description": "port ok"})
    monitor.rc_path().parent.mkdir(parents=True, exist_ok=True)
    monitor.rc_path().write_text("x", encoding="utf-8")

    def run(argv, **kw):
        assert argv[1:] == ["-c", str(monitor.rc_path()), "summary"]
        return subprocess.CompletedProcess(argv, 0, "Service Name   Status   Type\nsystem_data    OK   Filesystem\n", "")
    section = monitor.morning(SINCE, run=run, which=lambda n: "/x/monit")
    conn = _store()
    r = morning.gather(conn, NOW, SINCE, beat=None, gh=_gh(), git=_git(), where=tmp_path,
                       lanes=lambda c: [], monitor=lambda since: section)
    text = "\n".join(morning_cmd.render(r))
    assert "monit     4 alert line(s)" in text and "system_data    OK   Filesystem" in text
    assert "growers: runs 9 GiB" in text and "old" not in text
    flagged = [n for n in r["needs"] if n.startswith("monit ")]
    assert len(flagged) == 1 and "disk system_data: space free 40 GB" in flagged[0]


def test_the_morning_brief_says_when_monit_is_absent(tmp_path):
    assert monitor.morning(SINCE, which=lambda n: None)["why"] == "monit is not installed"
    conn = _store()
    r = _report(conn, tmp_path)
    assert r["monitor"] is None and not any("monit" in ln for ln in morning_cmd.render(r))


def test_install_is_macos_only_and_needs_monit(monkeypatch):
    with pytest.raises(monitor.InstallError, match="macOS-only"):
        monitor.install(platform="linux")
    with pytest.raises(monitor.InstallError, match="brew install monit"):
        monitor.install(which=lambda n: None, platform="darwin")


def test_status_reports_a_stale_config_and_a_loose_env_file(tmp_path):
    monitor.write_rc("old\n")
    p = monitor.env_path()
    p.write_text(f"{monitor.WEBHOOK}=http://x/{SECRET}\n", encoding="utf-8")
    p.chmod(0o644)
    got = monitor.status(run=lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "no socket"),
                         which=lambda n: "/x/monit", expected="new\n")
    text = "\n".join(got["problems"])
    assert got["current"] is False and "not what soh monitor install renders now" in text
    assert "monit is not running" in text and "make it 600" in text and got["webhook"] is True
    assert SECRET not in json.dumps(got)


@pytest.mark.skipif(sys.platform == "win32", reason="monit and its check script are POSIX")
@pytest.mark.parametrize("level,rc", [("1", 0), ("2", 1), ("4", 1), ("", 0)])
def test_the_pressure_check_fails_past_normal_only(tmp_path, level, rc):
    (tmp_path / "sysctl").write_text(f"#!/bin/sh\necho '{level}'\n", encoding="utf-8")
    (tmp_path / "sysctl").chmod(0o755)
    got = subprocess.run([shells.resolve("bash"), str(REPO / "scripts" / "monit-pressure.sh")], capture_output=True, text=True,
                         env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin"}, timeout=30)
    assert got.returncode == rc and (level or "unknown") in got.stdout
