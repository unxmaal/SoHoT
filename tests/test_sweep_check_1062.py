"""`soh sweep-check`: tonight's sweep from launchd state and the loop heartbeat, notified only when unhealthy. #1062."""
from __future__ import annotations

import json
import plistlib
import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from harness import heartbeat, morning
from harness import memory_store as ms
from harness import sweep_check as sc
from harness.commands import morning as morning_cmd
from tests import shells
from tests.gauntlet import scanners

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "launchctl"
START = datetime(2026, 10, 19, 21, 0).timestamp()
AT_22 = datetime(2026, 10, 19, 22, 0).timestamp()


def unit(name: str) -> dict:
    return sc.parse_launchctl((FIX / f"discover-{name}.txt").read_text(encoding="utf-8"))


def beat(state="running", started=START + 5, updated=None, rc=None, finished=None, step=3, total=10, pid=4242,
         deadline_s=None):
    return {"state": state, "pid": pid, "lane": "", "tier": "measure", "candidate": "llamacpp:Ornith-1.5-35B",
            "step": step, "total": total, "item": 1, "items": 5, "started": started,
            "updated": updated if updated is not None else started + 600, "finished": finished, "rc": rc,
            "error": "", "deadline_s": deadline_s, "waiting": ""}


def judge(u, b, now=AT_22, alive=lambda pid: True):
    return sc.verdict(u, b, now, START, alive=alive)


def test_the_real_launchctl_print_parses_to_its_top_level_fields():
    assert unit("not-running") == {"loaded": True, "state": "not running", "pid": None, "runs": 0, "rc": None,
                                   "signal": ""}
    assert unit("running")["state"] == "running" and unit("running")["pid"] == 41207
    assert unit("exited-1")["rc"] == 1 and unit("exited-1")["runs"] == 1


def test_a_running_unit_with_a_fresh_heartbeat_is_running_and_progressing():
    got = judge(unit("running"), beat(updated=AT_22 - 300))
    assert got["verdict"] == sc.RUNNING, got
    assert "measure, step 3 of 10" in got["line"]


def test_a_running_unit_whose_heartbeat_is_older_than_the_knob_is_stalled():
    got = judge(unit("running"), beat(updated=AT_22 - sc.STALL_S - 60))
    assert got["verdict"] == sc.STALLED and "no progress for" in got["line"]


def test_a_step_with_a_longer_declared_deadline_is_not_stalled_inside_it():
    got = judge(unit("running"), beat(updated=AT_22 - sc.STALL_S - 60, deadline_s=sc.STALL_S * 3))
    assert got["verdict"] == sc.RUNNING


def test_a_sweep_that_exited_nonzero_says_what_it_was_doing():
    got = judge(unit("exited-1"), beat(state="finished", rc=1, finished=START + 1200, updated=START + 1200))
    assert got["verdict"] == sc.EXITED
    assert "rc 1" in got["line"] and "measure, step 3 of 10" in got["line"]


def test_a_loop_that_died_without_finishing_is_exited_with_launchds_exit_code():
    got = judge(unit("exited-1"), beat(), alive=lambda pid: False)
    assert got["verdict"] == sc.EXITED and "last exit code 1" in got["line"]


def test_no_heartbeat_since_the_scheduled_start_is_never_started():
    got = judge(unit("not-running"), beat(state="finished", rc=0, started=START - 86400,
                                          finished=START - 60000))
    assert got["verdict"] == sc.NEVER and "21:00" in got["line"]
    assert judge(unit("not-running"), None)["verdict"] == sc.NEVER


def test_a_quick_clean_finish_is_early_and_a_full_one_is_finished():
    early = judge(unit("not-running"), beat(state="finished", rc=0, finished=START + 300, step=10))
    assert early["verdict"] == sc.EARLY
    short = judge(unit("not-running"), beat(state="finished", rc=0, finished=START + 7200, step=4))
    assert short["verdict"] == sc.EARLY and "step 4 of 10" in short["line"]
    done = judge(unit("not-running"), beat(state="finished", rc=0, finished=START + 6 * 3600, step=10),
                 now=START + 7 * 3600)
    assert done["verdict"] == sc.FINISHED


def test_an_unloaded_unit_and_a_platform_without_launchd():
    assert judge({"loaded": False, "why": "Could not find service"}, None)["verdict"] == sc.UNLOADED
    assert judge(None, None)["verdict"] == sc.UNSUPPORTED
    assert sc.launchd(platform="linux") is None


def test_the_probe_reads_the_discover_unit_from_launchctl_print(monkeypatch):
    seen = []

    def run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, (FIX / "discover-running.txt").read_text(encoding="utf-8"), "")
    got = sc.launchd(run=run, platform="darwin", uid=501)
    assert seen[0][:2] == ["launchctl", "print"] and seen[0][2] == "gui/501/com.unxmaal.localharness.discover"
    assert got["pid"] == 41207


def test_a_darwin_probe_with_no_getuid_is_unknown_without_asking_launchctl(monkeypatch):
    monkeypatch.delattr(sc.os, "getuid", raising=False)
    seen = []
    got = sc.launchd(run=lambda argv, **kw: seen.append(argv), platform="darwin")
    assert seen == [] and got["loaded"] is None
    assert judge(got, None)["verdict"] == sc.UNKNOWN


def test_tonight_is_the_latest_scheduled_start_before_now():
    assert sc.tonight(AT_22, [21]) == START
    assert sc.tonight(datetime(2026, 10, 20, 3, 0).timestamp(), [21]) == START
    assert sc.tonight(datetime(2026, 10, 20, 6, 0).timestamp(), [21]) == START


def _run(conn, u, b, now, sent):
    r = sc.check(now=now, unit=u, beat=b, hours=[21], alive=lambda pid: True)
    return sc.record(conn, r, notify=lambda *a: sent.append(a) or f"notified: {a[1]}")


def test_a_quiet_healthy_night_sends_nothing_and_records_every_check():
    conn, sent = ms.connect(), []
    for h in (22, 23, 24, 25, 26):
        now = START + (h - 21) * 3600
        _run(conn, unit("running"), beat(updated=now - 120), now, sent)
    end = START + 9 * 3600
    for h in (3, 4, 5, 6):
        _run(conn, unit("not-running"), beat(state="finished", rc=0, finished=START + 5.5 * 3600, step=10,
                                             updated=START + 5.5 * 3600), end, sent)
    assert sent == []
    got = sc.rows(conn, START)
    assert [r["verdict"] for r in got] == [sc.RUNNING] * 5 + [sc.FINISHED] * 4
    assert not any(r["notified"] for r in got)


def test_an_unhealthy_verdict_notifies_once_until_it_changes():
    conn, sent = ms.connect(), []
    stale = beat(updated=START + 60)
    first = _run(conn, unit("running"), stale, START + 3 * 3600, sent)
    again = _run(conn, unit("running"), stale, START + 4 * 3600, sent)
    died = _run(conn, unit("exited-1"), beat(state="finished", rc=1, finished=START + 4.5 * 3600), START + 5 * 3600,
                sent)
    assert first["notified"] and not again["notified"] and died["notified"]
    assert [a[2] for a in sent] == [f"discover sweep: {sc.STALLED}", f"discover sweep: {sc.EXITED}"]
    assert "notify held" in again["outcome"]


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/sweep_check.py:previous")
def test_the_last_check_is_tonights_on_this_machine_and_the_newest_row_on_a_tie():
    conn, sent = ms.connect(), []
    _run(conn, unit("not-running"), None, START - 86400 + 3600, sent)
    assert sc.previous(conn, START) == ""
    conn.execute("INSERT INTO machines (id, fingerprint, first_seen, last_seen) VALUES (999, 'Other1,1/macOS/arm64/other', 0, 0)")
    conn.execute("INSERT INTO watchdog_actions (at, machine_id, criterion, subject, action, escalated, dry_run, "
                 "evidence, outcome) VALUES (?, 999, ?, ?, 'note', 0, 0, ?, '')",
                 (AT_22, sc.CRITERION, sc.SUBJECT, json.dumps({"verdict": sc.STALLED})))
    assert sc.previous(conn, START) == ""
    _run(conn, unit("running"), beat(updated=AT_22 - 60), AT_22, sent)
    _run(conn, unit("not-running"), None, AT_22, sent)
    assert sc.previous(conn, START) == sc.NEVER


def test_never_started_notifies_at_the_first_check():
    conn, sent = ms.connect(), []
    got = _run(conn, unit("not-running"), None, AT_22, sent)
    assert got["notified"] and sent[0][0] == sc.NOTIFY_TITLE


def test_soh_morning_shows_the_nights_checks_and_a_stall_needs_a_person():
    conn, sent = ms.connect(), []
    _run(conn, unit("running"), beat(updated=START + 60), START + 3 * 3600, sent)
    _run(conn, unit("not-running"), beat(state="finished", rc=0, finished=START + 6 * 3600, step=10,
                                         updated=START + 6 * 3600), START + 9 * 3600, sent)
    r = morning.gather(conn, START + 9.5 * 3600, START - 3600, gh=lambda a: "[]", lanes=lambda c: [],
                       stalls=lambda c: [])
    assert [c["verdict"] for c in r["checks"]] == [sc.STALLED, sc.FINISHED]
    assert not any(w["criterion"] == sc.CRITERION for w in r["watchdog"])
    lines = morning_cmd.render(r)
    assert any(ln.startswith("checks    2 sweep check(s)") for ln in lines)
    assert any("00:00 stalled" in ln and "[notified]" in ln for ln in lines)
    assert any("sweep check" in n and "stalled" in n for n in r["needs"])


def test_the_unit_runs_at_22_and_hourly_to_06(tmp_path):
    subprocess.run([shells.resolve("bash"), str(REPO / "scripts" / "launchd.sh"), "generate", str(tmp_path)], check=True,
                   capture_output=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                                             "LOCALHARNESS_HOME": str(tmp_path / "lh")})
    plist = plistlib.loads((tmp_path / "com.unxmaal.localharness.sweep-check.plist").read_bytes())
    assert [(c["Hour"], c["Minute"]) for c in plist["StartCalendarInterval"]] == \
        [(h, 0) for h in (22, 23, 0, 1, 2, 3, 4, 5, 6)]
    assert plist["ProgramArguments"][-1].endswith("scripts/serve-sweep-check.sh")
    assert "soh sweep-check --notify" in (REPO / "scripts" / "serve-sweep-check.sh").read_text(encoding="utf-8")


#: Supervision code that predates #1062 and still shells out to pgrep; never add to it.
PGREP_KNOWN = {"scripts/h3-weights-status.sh"}


def _pgrep(text, rel):
    return [rel] if re.search(r"\bpgrep\b", text) else []


def test_no_supervision_code_reads_process_state_with_pgrep():
    found = set(scanners.scan_tree(REPO, _pgrep, lambda p: p.suffix in (".py", ".sh"),
                                   lambda rel: rel.startswith(("harness/", "scripts/"))))
    assert found <= PGREP_KNOWN, sorted(found - PGREP_KNOWN)


def test_the_pgrep_scan_keys_files_by_posix_path_under_windows_separators(windows_relative_paths):
    test_no_supervision_code_reads_process_state_with_pgrep()


def test_the_cli_prints_the_verdict_and_records_only_with_notify(monkeypatch, capsys):
    from harness import cli
    monkeypatch.setattr(sc, "launchd", lambda *a, **k: unit("not-running"))
    monkeypatch.setattr(heartbeat, "read", lambda: None)
    sent = []
    monkeypatch.setattr("harness.watchdog.desktop", lambda *a, **k: sent.append(a) or "notified: x")
    assert cli.main(["sweep-check", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == sc.NEVER and "recorded" not in out and sent == []
    assert cli.main(["sweep-check", "--notify"]) == 0
    assert len(sent) == 1
    conn = ms.connect()
    assert [r["verdict"] for r in sc.rows(conn, 0)] == [sc.NEVER]


@pytest.mark.parametrize("name", ["sweep_check_early", "sweep_check_stall", "sweep_check_start_slack"])
def test_each_threshold_is_a_registered_knob(name):
    from harness import knobs
    assert name in knobs.KNOBS
