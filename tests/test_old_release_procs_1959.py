"""After a deploy, the live processes still on another release are named with pid and release, never killed. #1959."""
from __future__ import annotations

import json
import subprocess
import sys


import pytest
from test_deploy_1506 import _Done, _inline, _queue, alerts, posix, world  # noqa: F401 - fixtures

from harness import cli, deploy, deploy_switch, holders, job_release, morning, release_procs
from harness import workqueue as wq
from harness.watchdog import Proc

OLD, NEW = "86-aaaaaaaaaaaa", "87-bbbbbbbbbbbb"


def _walk(root, places: dict, seen: list):
    def paths_of(pid):
        seen.append(("paths", pid))
        for how, rel in places[pid]:
            yield how, rel if rel.startswith("/") else f"{root}/{rel}"
    return list(places), paths_of, lambda pid: f"proc{pid}"


def _scan(tmp_path, places, same, me=999):
    root = tmp_path / "releases"
    root.mkdir(exist_ok=True)
    seen = []

    def identity(pid):
        seen.append(("identity", pid))
        return {"pid": pid, "pgid": pid, "started": f"t{pid}"}
    got = release_procs.scan(root, NEW, walk=_walk(root, places, seen), identity=identity,
                             same=lambda rec: same.get(rec["pid"], True), me=me)
    return {p["pid"]: p for p in got}, seen


def test_each_process_is_named_by_the_release_its_strongest_path_lies_in(tmp_path):
    places = {
        10: [("cwd", f"{OLD}"), ("mapped file", f"{OLD}/.venv/lib/x.so")],
        11: [("cwd", f"{NEW}")],
        12: [("cwd", f"{OLD}"), ("mapped file", f"{NEW}/.venv/lib/x.so")],
        13: [("cwd", f"{OLD}/evals")],
        14: [("open fd 3", f"{OLD}/runs/x.jsonl")],
        15: [("cwd", f"{OLD}")],
        16: [("cwd", "/elsewhere/x")],
        999: [("cwd", f"{OLD}")],
    }
    got, seen = _scan(tmp_path, places, {14: None, 15: False})
    assert set(got) == {10, 13, 14}, "serving-code, gone, unrelated and this process itself are not named"
    assert (got[10]["release"], got[10]["how"], got[10]["code"], got[10]["state"]) == (
        OLD, "mapped file", True, release_procs.STALE)
    assert (got[13]["how"], got[13]["code"]) == ("cwd", False)
    assert got[14]["state"] == release_procs.UNKNOWN, "same() None is unknown, never stale"
    assert seen.index(("identity", 10)) < seen.index(("paths", 10)), "identity is taken before the paths are read"


def test_an_unknown_process_is_never_said_to_run_the_old_release(tmp_path):
    got, _ = _scan(tmp_path, {14: [("mapped file", f"{OLD}/.venv/x.so")]}, {14: None})
    text = release_procs.line(got[14], NEW)
    assert "may still run release" in text and " runs " not in text and "unknown" in text


def test_a_cwd_only_process_sits_in_the_release_and_is_left_out_of_alerts(tmp_path):
    got, _ = _scan(tmp_path, {13: [("cwd", OLD)], 10: [("executable", f"{OLD}/bin/x")]}, {})
    r = {"serving": NEW, "procs": list(got.values())}
    assert any("pid 13 has its cwd in older release" in x for x in release_procs.lines(r))
    assert [x.split()[1] for x in release_procs.lines(r, code_only=True)] == ["10"]


def test_a_release_path_on_windows_matches_either_separator_and_any_case(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert release_procs.release_in(r"C:\LH\releases\5-abc\.venv\python.exe", "c:/lh/releases") == "5-abc"
    assert release_procs.release_in(r"C:\LH\releases-old\5-abc", "c:/lh/releases") == ""


class _Probes:
    def __init__(self, procs, listing):
        self.procs, self.listing, self.asked = procs, listing, []

    def processes(self):
        return self.procs

    def mcp_connections(self, port):
        self.asked.append(port)
        return self.listing


def test_an_mcp_server_on_an_old_release_names_the_clients_it_still_holds():
    root = job_release.releases_dir()
    (root / OLD).mkdir(parents=True)
    (root / NEW).mkdir()
    table = [Proc(20, 1, 20, 7200.0, f"{root}/{OLD}/.venv/bin/python -m harness.mcp_server --port 8899"),
             Proc(30, 1, 30, 3600.0, "claude --resume work")]
    listing = "p20\nn127.0.0.1:8899->127.0.0.1:50001\np30\nn127.0.0.1:50001->127.0.0.1:8899\n"
    probes = _Probes(table, listing)
    walk = ([20, 30], lambda pid: iter([("mapped file", f"{root}/{OLD}/x.so")] if pid == 20 else []), str)
    r = release_procs.report(serving=root / NEW, probes=probes, walk=walk, identity=lambda pid: {"pid": pid},
                             same=lambda rec: True)
    assert probes.asked == [8899]
    text = release_procs.lines(r)
    assert text[0].startswith("pid 20 (up 2.0h) runs older release") and "harness.mcp_server" in text[0]
    assert text[1].startswith("  its client pid 30") and "claude --resume work" in text[1]


@pytest.fixture
def child(tmp_path):
    procs = []

    def start(cwd):
        cwd.mkdir(parents=True, exist_ok=True)
        (cwd / "held").write_text("x", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-c", "import time; f = open('held'); print('up', flush=True); "
                              "time.sleep(120)"], cwd=cwd, stdout=subprocess.PIPE, text=True)
        assert p.stdout.readline().strip() == "up"
        procs.append(p)
        return p
    yield start
    for p in procs:
        p.kill()
        p.wait(timeout=10)


needs_walk = pytest.mark.skipif(holders.walkers() is None, reason="no process walk on this platform")


@needs_walk
def test_a_real_process_started_in_an_older_release_is_named_with_its_pid_and_release(child):
    root = job_release.releases_dir()
    old, new = child(root / OLD), child(root / NEW)
    r = release_procs.report(serving=root / NEW)
    got = {p["pid"]: p for p in r["procs"]}
    assert old.pid in got and new.pid not in got
    assert (got[old.pid]["release"], got[old.pid]["state"], got[old.pid]["code"]) == (OLD, release_procs.STALE, True)
    assert got[old.pid]["how"].startswith("open fd")


@posix
@needs_walk
@pytest.mark.sqlite_store
@pytest.mark.parametrize("migrated", [True, False])
def test_a_migrating_deploy_alerts_at_settle_naming_the_process_left_on_the_old_release(world, alerts, child,
                                                                                       migrated):
    old = child(world["link"])
    job = _queue(world, {"f": "two\n"})

    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        return _Done(deploy.run(argv[-1], job["id"], link=world["link"], steps=world["steps"], spawn=_inline))
    wq.run_one(job, popen=popen)
    path = sorted(deploy.records_dir().glob("*.json"))[-1]
    rec = deploy_switch.load(path)
    assert rec["outcome"] == deploy.DEPLOYED
    if migrated:
        rec.update(migrated=True, schema_to=123)
        deploy_switch.save(path, rec)
    assert [d["outcome"] for d in wq.settle_deploys()] == [deploy.DEPLOYED]
    said = [a for a in alerts if "still run another release" in a]
    if not migrated:
        assert said == []
        return
    assert len(said) == 1 and f"pid {old.pid} " in said[0] and "release adopted-" in said[0]
    assert "schema 123" in said[0] and old.poll() is None, "named, never killed"
    assert wq.settle_deploys() == [] and len([a for a in alerts if "still run another release" in a]) == 1


def test_morning_names_old_release_code_as_a_need_and_in_its_report(tmp_path):
    from test_morning_867 import NOW, SINCE, _beat, _gh, _git, _store
    from harness.commands import morning as morning_cmd
    r = {"serving": NEW, "procs": [
        {"pid": 41, "name": "python", "release": OLD, "how": "mapped file", "path": "p", "code": True,
         "state": release_procs.STALE, "started": "", "command": "python -m evals.run --lane code"},
        {"pid": 42, "name": "zsh", "release": OLD, "how": "cwd", "path": "p", "code": False,
         "state": release_procs.STALE, "started": ""}]}
    got = morning.gather(_store(), NOW, SINCE, beat=_beat(), gh=_gh(), git=_git(), where=tmp_path,
                         lanes=lambda c: [], old=lambda: r)
    need = [n for n in got["needs"] if n.startswith("old code:")]
    assert len(need) == 1 and "pid 41 runs older release" in need[0] and "evals.run" in need[0]
    text = "\n".join(morning_cmd.render(got))
    assert "old code  2 process(es) on another release" in text and "pid 42 has its cwd in" in text


def test_deploy_status_lists_the_processes_on_another_release(monkeypatch, capsys):
    seen = []
    r = {"serving": NEW, "procs": [{"pid": 51, "name": "python", "release": OLD, "how": "executable", "path": "p",
                                    "code": True, "state": release_procs.STALE, "started": ""}]}
    monkeypatch.setattr(release_procs, "report", lambda serving=None: seen.append(serving) or r)
    assert cli.main(["deploy", "status", "--json"]) == 0
    out = capsys.readouterr()
    assert "old code: pid 51 runs older release" in out.err + out.out
    assert json.loads(out.out.strip().splitlines()[-1])["old_release"]["procs"][0]["pid"] == 51
    assert len(seen) == 1


def test_a_platform_that_cannot_walk_processes_says_so_and_alerts_nothing(monkeypatch, tmp_path):
    root = job_release.releases_dir()
    (root / OLD).mkdir(parents=True)
    (root / NEW).mkdir()
    monkeypatch.setattr(sys, "platform", "win32")
    r = release_procs.report(serving=root / NEW)
    assert r["procs"] is None and "no way to tell" in release_procs.lines(r)[0]
    assert release_procs.after_deploy({"migrated": True, "release": str(root / NEW)},
                                      report_=lambda serving: r) == ""


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/holders.py:walkers:except")
def test_a_libproc_that_will_not_load_cannot_tell_which_is_not_nothing_found(monkeypatch):
    def broken():
        raise OSError("no libproc")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(holders, "_libproc", broken)
    root = job_release.releases_dir()
    (root / OLD).mkdir(parents=True)
    (root / NEW).mkdir()
    assert holders.walkers() is None and holders.holding([root / OLD]) is None and holders.holding([]) == {}
    assert release_procs.report(serving=root / NEW)["procs"] is None, "cannot tell, not 'no process found'"
