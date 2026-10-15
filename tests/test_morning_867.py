"""`soh morning`: last night in one report, a notification only when something needs a person. #867."""
from __future__ import annotations

import json
import plistlib
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness import delegate, morning
from harness import memory_store as ms
from harness.commands import morning as morning_cmd
from tests import shells

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 15, 6, 30).timestamp()
SINCE = NOW - 18 * 3600
NIGHT = datetime(2026, 10, 14, 21, 0).timestamp()
YESTERDAY = datetime(2026, 10, 14).strftime("%Y-%m-%d")


def _gh(run_conclusion="success", jobs=(("check-macos", "success"), ("check-linux", "success")), created=None):
    created = created or datetime.fromtimestamp(NOW - 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = [{"databaseId": 42, "status": "completed", "conclusion": run_conclusion, "createdAt": created,
             "headSha": "f4f9566b12fa804087c150d1ce7bd30ef627e8aa", "url": "https://x/runs/42"}]
    view = {"jobs": [{"name": n, "status": "completed", "conclusion": c, "url": f"https://x/{n}"} for n, c in jobs]}

    def gh(argv):
        assert argv[:2] in (["run", "list"], ["run", "view"]), argv
        if argv[:2] == ["run", "list"]:
            assert argv[argv.index("--workflow") + 1] == morning.NIGHTLY_WORKFLOW
            assert argv[argv.index("--event") + 1] == "schedule"
            return json.dumps(runs)
        assert argv[2] == "42"
        return json.dumps(view)
    return gh


def _git(behind=0):
    def git(argv):
        cmd = argv[2:]
        if cmd[0] == "fetch":
            return ""
        if cmd == ["rev-parse", "HEAD"]:
            return "a" * 40
        if cmd == ["rev-parse", "origin/main"]:
            return ("b" if behind else "a") * 40
        if cmd[0] == "rev-list":
            return str(behind)
        if cmd[0] == "log":
            return "\n".join(f"b{i:07d} commit {i}" for i in range(behind))
        raise AssertionError(cmd)
    return git


@pytest.fixture
def deploy_dir(tmp_path):
    d = tmp_path / "deploy"
    (d / ".git").mkdir(parents=True)
    return d


def _beat(rc=0, started=NIGHT):
    return {"state": "finished", "status": "finished", "rc": rc, "error": "", "started": started,
            "finished": started + 3600, "line": f"last discovery loop finished 8h ago, rc {rc}"}


def _store(stops=0, ledger=True):
    conn = ms.connect()
    conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at) VALUES (NULL,'screened','screen','',?)",
                 (NIGHT + 60,))
    conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at) VALUES (NULL,'broken','screen','',?)",
                 (NIGHT + 70,))
    conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at) VALUES (NULL,'declined','adopt','',?)",
                 (NIGHT + 7200,))
    conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at) VALUES (NULL,'screened','screen','',?)",
                 (SINCE - 3600,))
    conn.execute("INSERT INTO runs (path, lane, tier, recorded_at) VALUES ('r-code','code','measure',?)", (NIGHT + 3000,))
    conn.execute("INSERT INTO runs (path, lane, tier, recorded_at) VALUES ('r-old','svg','measure',?)", (SINCE - 60,))
    conn.execute("INSERT INTO paused_runs (lane, incumbent, challenger, out, done, total, state, paused_at) "
                 "VALUES ('code','inc','chal','o',114,270,'paused',?)", (NIGHT + 5000,))
    conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action, escalated, dry_run, outcome) "
                 "VALUES (?, 'overrun', 'eval pgid 1', 'file', 0, 0, 'not filed')", (NIGHT + 900,))
    for i in range(stops):
        conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action, escalated, dry_run, outcome) "
                     "VALUES (?, 'overrun', ?, 'stop', 1, 0, 'group term')", (NIGHT + 1500 + i, f"eval pgid {i + 2}"))
    if ledger:
        conn.execute("INSERT INTO ledger_days (day, recorded_at, cloud_usd, displaced_usd, mapped_usd, tier, energy_kwh) "
                     "VALUES (?, ?, 35.76, 0.0, NULL, 'sonnet', 0.06)", (YESTERDAY, NIGHT + 7200))
    conn.commit()
    return conn


def _report(conn, deploy_dir, *, beat=None, gh=None, behind=0, stale=()):
    return morning.gather(conn, NOW, SINCE, beat=_beat() if beat is None else beat, gh=gh or _gh(),
                          git=_git(behind), where=deploy_dir, lanes=lambda c: list(stale))


def test_a_fixture_night_produces_the_expected_report(deploy_dir):
    conn = _store(stops=1)
    gh = _gh(run_conclusion="failure", jobs=(("check-macos", "success"), ("check-windows", "failure")))
    r = _report(conn, deploy_dir, gh=gh, behind=2,
                stale=[{"lane": "tts", "candidate": "k", "why": "last measured 7 days ago", "skip": ""}])
    s = r["sweep"]
    assert s["screened"] == {"broken": 1, "screened": 1}
    assert [x["lane"] for x in s["measured"]["runs"]] == ["code"]
    assert s["settled"]["verdicts"] == {"declined": 1}
    assert [(p["lane"], p["done"], p["total"]) for p in s["paused"]] == [("code", 114, 270)]
    assert [w["subject"] for w in s["stopped"]] == ["eval pgid 2"]
    assert len(r["watchdog"]) == 2
    assert r["ci"]["available"] and r["ci"]["fresh"]
    assert {j["name"]: j["conclusion"] for j in r["ci"]["jobs"]} == {"check-macos": "success",
                                                                    "check-windows": "failure"}
    assert r["ledger"]["day"] == YESTERDAY and r["ledger"]["cloud_usd"] == pytest.approx(35.76)
    assert r["deploy"]["behind"] == 2 and len(r["deploy"]["missing"]) == 2
    assert r["needs"] == [
        "watchdog stop: overrun on eval pgid 2 at 21:25",
        "nightly CI failed: check-windows",
        "deploy is 2 commit(s) behind origin/main",
        "stale lanes: tts",
    ]
    text = "\n".join(morning_cmd.render(r))
    for want in ("screened  broken 1, screened 1", "measured  1 run(s): code", "paused    #1 code chal paused at 114/270",
                 "stopped   1", "settled   declined 1", "watchdog  2 action(s)", "failure    check-windows",
                 f"ledger    {YESTERDAY}: cloud $35.76", "stale     1 lane(s)", "2 commit(s) behind"):
        assert want in text, want


def test_a_quiet_night_sends_no_notification(deploy_dir):
    conn = _store()
    r = _report(conn, deploy_dir)
    assert r["needs"] == []
    sent = []
    assert morning.notify(r, "anything", run=lambda *a, **k: sent.append(a), platform="darwin") is None
    assert sent == []
    head = morning.headline(r, "facts", ask=lambda p: pytest.fail("a quiet night needs no model"))
    assert head["by"] == "deterministic" and head["text"].startswith("Quiet night: 2 screened, 1 measured, 1 settled")


def test_a_watchdog_stop_sends_one_notification(deploy_dir):
    conn = _store(stops=1)
    r = _report(conn, deploy_dir)
    assert r["needs"] == ["watchdog stop: overrun on eval pgid 2 at 21:25"]
    sent = []

    def run(argv, **kw):
        sent.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    got = morning.notify(r, "watchdog stopped a run", run=run, platform="darwin")
    assert got.startswith("notified")
    assert len(sent) == 1 and sent[0][0] == "osascript"
    assert sent[0][-3:] == [morning.NOTIFY_TITLE, "watchdog stopped a run", "1 thing(s) need you"]


@pytest.mark.parametrize("beat, want", [
    ({"rc": 1}, "the sweep exited 1"),
    ({"status": "stalled", "rc": None}, "the sweep stalled"),
    ({"started": SINCE - 86400}, "no discovery sweep ran last night"),
])
def test_a_sweep_that_failed_or_never_ran_needs_a_person(deploy_dir, beat, want):
    conn = _store()
    r = _report(conn, deploy_dir, beat={**_beat(), **beat})
    assert len(r["needs"]) == 1 and r["needs"][0].startswith(want)


def test_no_heartbeat_at_all_needs_a_person(deploy_dir):
    r = morning.gather(_store(), NOW, SINCE, beat=None, gh=_gh(), git=_git(), where=deploy_dir, lanes=lambda c: [])
    assert r["needs"] == ["no discovery sweep ran last night"]


def test_an_old_nightly_failure_is_shown_and_not_notified(deploy_dir):
    old = datetime.fromtimestamp(NOW - morning.CI_FRESH_S - 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = _report(_store(), deploy_dir, gh=_gh("failure", (("check-windows", "failure"),), created=old))
    assert not r["ci"]["fresh"] and r["needs"] == []
    assert "not last night's" in "\n".join(morning_cmd.render(r))


def test_unavailable_ci_and_deploy_are_reported_not_notified(tmp_path):
    def gh(argv):
        raise RuntimeError("gh run list: rc 4: auth required")
    r = morning.gather(_store(), NOW, SINCE, beat=_beat(), gh=gh, git=_git(), where=tmp_path / "none",
                       lanes=lambda c: [])
    assert r["ci"] == {"available": False, "why": "gh run list: rc 4: auth required"}
    assert not r["deploy"]["available"] and r["needs"] == []


def test_a_dry_run_escalation_still_needs_a_person(deploy_dir):
    conn = _store()
    conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action, escalated, dry_run, outcome) "
                 "VALUES (?, 'no_progress', 'job 0042', 'stop', 1, 1, 'dry-run')", (NIGHT + 100,))
    conn.commit()
    r = _report(conn, deploy_dir)
    assert r["needs"] == ["watchdog stop (dry run): no_progress on job 0042 at 21:01"]


def test_the_headline_is_the_models_and_falls_back_when_it_refuses(deploy_dir):
    r = _report(_store(stops=2), deploy_dir, behind=1)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return "Two watchdog stops overnight.\nDeploy 1 behind.\n\nextra\nmore"
    head = morning.headline(r, "FACTS", ask=ask)
    assert head == {"text": "Two watchdog stops overnight.\nDeploy 1 behind.\nextra", "by": "model", "why": ""}
    assert "FACTS" in asked[0] and all(n in asked[0] for n in r["needs"])

    def refuse(prompt):
        raise delegate.Refused("this machine is busy with infovore")
    head = morning.headline(r, "FACTS", ask=refuse)
    assert head["by"] == "deterministic" and "busy with infovore" in head["why"]
    assert head["text"].splitlines()[:3] == r["needs"][:3]
    assert morning.headline(r, "FACTS", ask=lambda p: "  \n")["by"] == "deterministic"


def test_the_model_is_not_asked_while_the_machine_is_held(monkeypatch):
    monkeypatch.setattr(delegate, "busy", lambda: "discover-loop (pid 9)")
    monkeypatch.setattr(delegate, "complete", lambda *a, **k: pytest.fail("asked the model under a held lock"))
    with pytest.raises(delegate.Refused, match="busy with discover-loop"):
        morning._ask("p")


def test_the_report_never_writes_the_live_store(tmp_path, monkeypatch):
    conn = _store()
    conn.close()
    path = ms.db_path()
    before = path.read_bytes()
    snap = morning.snapshot()
    try:
        snap.execute("INSERT INTO candidates (spec, receipt_key, lane, created_at) VALUES ('x','x','code',0)")
        snap.commit()
        assert snap.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == 4
    finally:
        snap.close()
    assert path.read_bytes() == before
    ro = sqlite3.connect(path)
    assert ro.execute("SELECT COUNT(*) FROM candidates WHERE spec = 'x'").fetchone()[0] == 0
    ro.close()


def test_the_morning_unit_fires_at_half_past_six_on_the_scheduler_only(tmp_path):
    gen = REPO / "scripts" / "launchd.sh"
    out = tmp_path / "units"
    out.mkdir()
    proc = subprocess.run([shells.BASH, str(gen), "generate", str(out)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    unit = plistlib.loads(next(out.glob("*.morning.plist")).read_bytes())
    assert unit["StartCalendarInterval"] == [{"Hour": 6, "Minute": 30}]
    assert unit["ProgramArguments"][1].endswith("serve-morning.sh")
    assert "--notify" in (REPO / "scripts" / "serve-morning.sh").read_text(encoding="utf-8")
    text = gen.read_text(encoding="utf-8")
    only = next(l for l in text.splitlines() if l.startswith("declare -a SCHEDULER_ONLY=("))
    assert "morning" in only.split("(", 1)[1].rstrip(")").split()


def test_the_cli_runs_end_to_end_without_notifying(monkeypatch, deploy_dir, capsys):
    from harness import cli, heartbeat, paths
    _store(stops=1).close()
    monkeypatch.setattr(morning, "_gh", _gh())
    monkeypatch.setattr(morning, "_git", _git())
    monkeypatch.setattr(morning, "stale_lanes", lambda c: [])
    monkeypatch.setattr(heartbeat, "summary", lambda: _beat(started=time.time() - 3600))
    monkeypatch.setattr(paths, "deploy_checkout", lambda: deploy_dir)
    monkeypatch.setattr(morning, "notify", lambda *a, **k: pytest.fail("notified without --notify"))
    assert cli.main(["morning", "--since", "3650d", "--no-model", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["needs"] == [n for n in got["needs"] if n.startswith("watchdog stop")] and got["needs"]
    assert got["headline"]["by"] == "deterministic" and got["notified"] is None
