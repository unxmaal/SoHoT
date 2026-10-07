"""soh volume stop|start|status and soh disk speed, against a fake launchctl, lsof and ps. #612."""
import json
import ntpath
import os
import subprocess
from pathlib import Path

import pytest

from harness import cli, paths, volume

VOL = "/Volumes/FAST"
P = volume.PREFIX


class Machine:
    """launchctl, lsof and ps as one small fake: services, their pids, open files."""

    def __init__(self, services, files=None, parents=None, sticky=()):
        self.services = dict(services)
        self.files = dict(files or {})
        self.parents = dict(parents or {})
        self.sticky = set(sticky)
        self.calls = []
        self.next_pid = 900

    def __call__(self, argv, **_kw):
        self.calls.append(list(argv))
        out, rc = "", 0
        if argv[:2] == ["launchctl", "list"]:
            out = "PID\tStatus\tLabel\n" + "".join(
                f"{pid or '-'}\t0\t{label}\n" for label, pid in self.services.items())
        elif argv[:2] == ["launchctl", "bootout"]:
            label = argv[2].rsplit("/", 1)[1]
            pid = self.services.pop(label, None)
            if pid is None:
                rc = 3
            elif label not in self.sticky:
                self.files = {p: f for p, f in self.files.items()
                              if p != pid and self.parents.get(p) != pid}
        elif argv[:2] == ["launchctl", "bootstrap"]:
            label = Path(argv[3]).stem
            self.next_pid += 1
            self.services[label] = self.next_pid
        elif argv[:2] == ["launchctl", "print"]:
            rc = 0 if argv[2].rsplit("/", 1)[1] in self.services else 113
        elif argv[0] == "lsof":
            out = "".join(f"p{pid}\nc{cmd}\nn{name}\n"
                          for pid, (cmd, name) in self.files.items())
            rc = 0 if out else 1
        elif argv[0] == "ps":
            out = "".join(f"{pid} {ppid}\n" for pid, ppid in self.parents.items())
        return subprocess.CompletedProcess(argv, rc, out, "")


def live():
    return Machine(
        {f"{P}.gateway": 10, f"{P}.mlx": 20, f"{P}.eval": 30, f"{P}.tts": 40,
         f"{P}.worker": 50, f"{P}.mcp": 60},
        files={21: ("Python", f"{VOL}/hf/hub/model.safetensors"),
               61: ("python", f"{VOL}/hf/hub/x")},
        parents={21: 20, 61: 60, 20: 1, 60: 1})


class Queue:
    def __init__(self, paused=False):
        self.paused, self.resumed = paused, 0

    def quiesce(self):
        was, self.paused = self.paused, True
        return was

    def resume(self):
        self.resumed += 1
        self.paused = False


def ops(m, q, mounted=True):
    return volume.Ops(run=m, quiesce=q.quiesce, resume=q.resume,
                      ismount=lambda p: mounted, sleep=lambda s: None)


def test_the_volume_is_the_mount_named_under_volumes_even_when_absent():
    assert volume.volume_of(f"{VOL}/hf") == VOL
    assert volume.volume_of(VOL) == VOL


def test_a_volume_path_is_read_as_posix_whatever_the_host_spells_paths(monkeypatch):
    monkeypatch.setattr(os.path, "abspath", ntpath.abspath)
    assert volume.volume_of(f"{VOL}/hf") == VOL
    assert volume.volume_of(f"{VOL}/a/../b") == VOL


def test_volume_is_macos_only_and_says_so_elsewhere(capsys, monkeypatch):
    assert volume.supported("darwin") is True
    assert volume.supported("linux") is False and volume.supported("win32") is False
    m = live()
    monkeypatch.setattr(volume, "default_ops", lambda: ops(m, Queue()))
    monkeypatch.setattr(volume, "supported", lambda: False)
    for action in ("status", "stop", "start"):
        assert cli.main(["volume", action, "--path", VOL]) == 1
        assert "macOS" in capsys.readouterr().err
    assert m.calls == []


def test_parsers_read_lsof_and_ps_fields():
    assert volume.parse_lsof("p5\ncpy\nn/a\nn/a\np6\ncsh\nf3\nn/b\n") == [
        (5, "py", "/a"), (6, "sh", "/b")]
    assert volume.parse_ps(" 5  1\n6 5\nbad\n") == {5: 1, 6: 5}
    assert volume.owner(7, {7: 6, 6: 5, 5: 1}, {5: "svc"}) == "svc"
    assert volume.owner(7, {7: 7}, {}) is None


def test_stop_stops_holders_model_servers_and_discover_and_records_it(tmp_path):
    m, q = live(), Queue()
    got = volume.stop(VOL, ops(m, q))
    assert set(got["stopped"]) == {f"{P}.mlx", f"{P}.eval", f"{P}.tts", f"{P}.mcp"}
    assert got["remaining"] == [] and got["was_paused"] is False
    assert f"{P}.gateway" in m.services and f"{P}.worker" in m.services
    saved = json.loads(volume.state_path().read_text(encoding="utf-8"))
    assert saved["volume"] == VOL and set(saved["stopped"]) == set(got["stopped"])


def test_stop_also_stops_a_loaded_discover_agent_between_runs():
    m, q = live(), Queue()
    m.services[f"{P}.discover"] = None
    got = volume.stop(VOL, ops(m, q))
    assert f"{P}.discover" in got["stopped"]


def test_stop_refuses_success_while_lsof_still_shows_open_files():
    m, q = live(), Queue()
    m.files[99] = ("Finder", f"{VOL}/notes.txt")
    m.parents[99] = 1
    got = volume.stop(VOL, ops(m, q))
    assert got["remaining"] == [(99, "Finder", f"{VOL}/notes.txt")]
    assert volume.state_path().exists()


def test_stop_cli_exits_nonzero_and_names_the_remaining_process(capsys, monkeypatch):
    m = live()
    m.sticky.add(f"{P}.mlx")
    q = Queue()
    monkeypatch.setattr(volume, "default_ops", lambda: ops(m, q))
    monkeypatch.setattr(volume, "supported", lambda: True)
    assert cli.main(["volume", "stop", "--path", VOL]) == 1
    text = capsys.readouterr()
    assert "21" in text.err and "model.safetensors" in text.err


def test_stop_keeps_the_owners_pause_and_start_does_not_resume_it():
    m, q = live(), Queue(paused=True)
    volume.stop(VOL, ops(m, q))
    volume.start(ops(m, q))
    assert q.resumed == 0 and q.paused is True


def test_start_restores_only_what_stop_stopped_and_resumes_a_running_queue():
    m, q = live(), Queue()
    stopped = set(volume.stop(VOL, ops(m, q))["stopped"])
    m.calls.clear()
    got = volume.start(ops(m, q))
    booted = {Path(c[3]).stem
              for c in m.calls if c[:2] == ["launchctl", "bootstrap"]}
    assert booted == stopped == set(got["started"])
    assert f"{P}.discover" not in booted
    assert q.resumed == 1
    assert not volume.state_path().exists()


def test_start_refuses_when_the_volume_is_not_mounted():
    m, q = live(), Queue()
    volume.stop(VOL, ops(m, q))
    m.calls.clear()
    with pytest.raises(volume.VolumeError, match="not mounted"):
        volume.start(ops(m, q, mounted=False))
    assert not [c for c in m.calls if c[:2] == ["launchctl", "bootstrap"]]
    assert volume.state_path().exists() and q.resumed == 0


def test_start_without_a_stop_does_nothing():
    with pytest.raises(volume.VolumeError, match="nothing to start"):
        volume.start(ops(live(), Queue()))


def test_status_names_services_and_processes_holding_files():
    got = volume.status(VOL, ops(live(), Queue()))
    assert got["mounted"] is True
    assert got["services"] == sorted([f"{P}.mlx", f"{P}.mcp"])
    assert {h["pid"] for h in got["holders"]} == {21, 61}


def test_disk_speed_records_volume_size_and_method(tmp_path, capsys):
    assert cli.main(["disk", "speed", str(tmp_path), "--mib", "4", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    rows = [json.loads(x) for x in volume.speed_log().read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["bytes"] == 4 * 1024 * 1024 and row["method"]
    assert row["volume"] == volume.volume_of(str(tmp_path))
    assert row["read_bytes_per_s"] > 0 and row["path"] == str(tmp_path)
    assert out["measurement"] == row
    assert not [p for p in tmp_path.iterdir()]


def test_disk_speed_runs_where_os_has_no_readv(tmp_path, monkeypatch):
    monkeypatch.delattr(os, "readv", raising=False)
    row = volume.speed(str(tmp_path), size=4 * 1024 * 1024)
    assert row["bytes"] == 4 * 1024 * 1024 and row["read_bytes_per_s"] > 0


def test_disk_speed_refuses_without_room(tmp_path, monkeypatch):
    monkeypatch.setattr(volume, "_free", lambda p: 1024)
    with pytest.raises(volume.VolumeError, match="free"):
        volume.speed(str(tmp_path), size=4 * 1024 * 1024)
    assert not volume.speed_log().exists()


def test_the_state_and_measurements_live_under_the_home():
    assert volume.state_path().parent == paths.home()
    assert volume.speed_log().parent == paths.home()
