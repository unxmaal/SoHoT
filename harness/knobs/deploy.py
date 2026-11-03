"""Knobs of the deploy guards in scripts/launchd.sh and of queue deploys (#870, #1000, #1058, #1506)."""
from harness.knobs.base import _k

M = "harness/deploy_guard.py"
S = "harness/sweep_guard.py"

Q = "harness/deploy.py"
X = "harness/deploy_switch.py"
DISK = "a release is a checkout plus its own .venv (436 MB measured on the Studio 2026-11-03, 186 GiB free)"
SMOKE = ("scripts/smoke.sh's own bounds: READY_TIMEOUT 120 s, then curl --max-time 10+30+2x60+2x300 s, about 880 s "
         "before its uv runs")

KNOBS = [
    _k("deploy_every", ["scripts/launchd.sh:DEPLOY_EVERY_MIN"], [5, 10, 30], unit="minutes",
       note="minutes between polls of origin/main for a green commit to queue; how late a merge becomes a deploy "
            "job. 2026-11-02: #1500-#1503 merged and waited a night with no deploy at all (#1506)"),
    _k("deploy_git_timeout", [f"{Q}:GIT_TIMEOUT_S"], [60.0, 300.0, 900.0], unit="s",
       note="seconds one git fetch, checkout or ls-files of a deploy may take; a timeout fails the deploy before "
            "the switch (#1506)"),
    _k("deploy_handoff_grace", [f"{Q}:HANDOFF_GRACE_S"], [60.0, 300.0, 900.0], unit="s",
       note="seconds a handed-off switch has to start and record its pid before settle calls the deploy "
            "interrupted; launchd starts a one-shot unit in under a second (#1506)"),
    _k("deploy_install_timeout", [f"{X}:INSTALL_TIMEOUT_S"], [1800.0, 3600.0, 7200.0], unit="s",
       note="seconds the new release's launchd.sh reinstall may take: worker quiesce, LH_DEFER_WAIT_S 120 per "
            "deferred unit, PREFLIGHT_WAIT_S 60, the audit; a timeout rolls back (#1506)"),
    _k("deploy_keep_releases", [f"{Q}:KEEP_RELEASES"], [2, 3, 5], unit="releases",
       note=f"release directories kept, the serving and previous one included; {DISK} (#1506)"),
    _k("deploy_last_start_hour", [f"{Q}:LAST_START_HOUR"], [18, 19, 20], unit="hours",
       note="local hour after which no deploy starts until the next day start; FINDING #587: the 2026-10-18 21:04 "
            "deploy raced the 21:00 sweep, which ran old code all night. Day-only until #1509"),
    _k("deploy_migrate_timeout", [f"{Q}:MIGRATE_TIMEOUT_S"], [600.0, 1800.0, 3600.0], unit="s",
       note="seconds the new release's migration of the live store may take before the backup is restored; "
            "FINDING #278: six stores up to schema 42 migrated in 0-2.1 s (#1506)"),
    _k("deploy_path_timeout", ["harness/paths.py:deploy_link->subprocess.run(timeout)"], [10, 30, 60], unit="s",
       note="seconds `launchd.sh deploy-path` may take to name the deploy link; a timeout reads as no deploy checkout. "
            "It sources nothing and prints one variable (#455, #1506)"),
    _k("deploy_smoke_timeout", [f"{Q}:SMOKE_TIMEOUT_S"], [900.0, 1200.0, 1800.0], unit="s",
       note=f"seconds smoke may take in the new release before the switch; {SMOKE} (#1506)"),
    _k("deploy_sync_timeout", [f"{Q}:SYNC_TIMEOUT_S"], [600.0, 1800.0, 3600.0], unit="s",
       note="seconds `uv sync --frozen` may take in a new release; measured 2026-11-03 on the Studio: 0.57 s into an "
            "empty env from a warm uv cache (400 MB); a cold cache downloads every wheel (#1506)"),
    _k("deploy_verify_timeout", [f"{X}:VERIFY_TIMEOUT_S"], [900.0, 1800.0, 3600.0], unit="s",
       note=f"seconds smoke or soh coherence may take on the live system after the switch; {SMOKE} (#1506)"),
    _k("lanprobe_instant_ms", ["harness/lanprobe.py:INSTANT_MS"], [100, 500, 2000],
       note="milliseconds under which a failed LAN connect reads as a denial, not a real no-route, which waits on ARP (#739)"),
]

NOT_GATING = {
    f"{Q}:LAUNCHCTL_TIMEOUT_S": "how long launchctl may take to load the switch's one-shot unit; a timeout fails "
                                "the deploy before the switch and restores the store (#1506)",
    f"{X}:ALERT_TIMEOUT_S": "how long the deploy alert script may take; the outcome is already recorded (#1506)",
    f"{X}:restore->sqlite3.connect(timeout)": "how long the restore waits for the store's lock; a timeout leaves "
                                              "the rollback saying the restore FAILED and alerts (#1506)",
    f"{Q}:recent(days)": "how far back soh deploy lists deploys; a listing, it gates nothing (#1506)",
    "scripts/launchd.sh:LH_DEFER_WAIT_S": "how long install waits for a live periodic run to end before reloading "
                                          "it; at the deadline the unit stays deferred and install fails (#1058)",
    f"{M}:GH_TIMEOUT_S": "how long gh may take to say whether check-macos passed; a timeout refuses the deploy (#870)",
    f"{S}:PS_TIMEOUT_S": "how long ps may take to name a pid's command; a slow ps leaves the pid counted as a "
                         "sweep, so the deploy refuses rather than guesses (#1000)",
    f"{S}:STOP_GRACE_S": "how long an overridden sweep has between TERM and KILL; the same role as "
                         "watchdog.STOP_GRACE_S (#1000)",
}

NEVER_CUTS = {
    "scripts/launchd.sh:DEPLOY_EVERY_MIN": "how often origin/main is polled; a schedule cuts no work (#1506)",
    f"{Q}:LAST_START_HOUR": "a deploy past it waits for the next day window and runs then; nothing is dropped (#1506)",
    f"{Q}:HANDOFF_GRACE_S": "past it a switch that never started is settled interrupted and alerted; the job ends "
                            "either way (#1506)",
    "scripts/launchd.sh:AUDIT_HOURS": "the hour the nightly audit unit starts; a schedule cuts no work (#1087)",
    "scripts/launchd.sh:DISCOVER_HOURS": "the hour the discovery loop starts; its ceiling, not its start, bounds it, "
                                         "a schedule cuts no work (#1087)",
    "harness/lanprobe.py:INSTANT_MS": "classes a failed connect as a denial or no route; the probe ran either way (#739)",
}
