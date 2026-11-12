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
    _k("deploy_engine_smoke_timeout", ["harness/engine_smoke.py:ASK_TIMEOUT_S"], [120.0, 300.0, 600.0], unit="s",
       note="seconds smoke's one completion per upstream engine may take, a cold model load included; it asks "
            "each engine's first model in the served config, 0.5B MLX and 4B GGUF on the Studio (#1518)"),
    _k("deploy_every", ["scripts/launchd.sh:DEPLOY_EVERY_MIN"], [1, 5, 10], unit="minutes",
       note="minutes between polls of origin/main for a green commit to queue; how late a merge becomes a deploy "
            "job. An idle poll is one git fetch and no gh call. 2026-11-10: #1682 waited 8 min on a 10 min poll "
            "(#1506, #1684)"),
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
    _k("deploy_migrate_timeout", [f"{Q}:MIGRATE_TIMEOUT_S"], [600.0, 1800.0, 3600.0], unit="s",
       note="seconds the new release's migration of the live store may take before the backup is restored; "
            "FINDING #278: six stores up to schema 42 migrated in 0-2.1 s (#1506)"),
    _k("deploy_node_drain", ["harness/node_deploy.py:DRAIN_S"], [30.0, 120.0, 300.0], unit="s",
       note="how long a node deploy waits for the node's in-flight requests, with the node out of the gateway's routing, before it restarts the node anyway; node lanes answer in seconds (#1815)"),
    _k("deploy_node_install_timeout", ["harness/node_deploy.py:INSTALL_TIMEOUT_S"], [900.0, 1800.0, 3600.0],
       unit="s", note="seconds a node's checkout, uv sync and launchd.sh reinstall over ssh may take; a timeout "
                      "rolls the node back to its previous checkout and alerts (#1692)"),
    _k("deploy_node_warm", ["harness/node_deploy.py:WARM_S"], [120.0, 300.0, 600.0], unit="s",
       note="seconds a reinstalled node has to answer /models before its install counts as failed and rolls back; "
            "its interactive unit loads two pinned GGUFs, about 11.6 GiB on the Mac mini node (#1692)"),
    _k("deploy_path_timeout", ["harness/paths.py:deploy_link->subprocess.run(timeout)"], [10, 30, 60], unit="s",
       note="seconds `launchd.sh deploy-path` may take to name the deploy link; a timeout reads as no deploy checkout. "
            "It sources nothing and prints one variable (#455, #1506)"),
    _k("deploy_probe_timeout", [f"{Q}:PROBE_TIMEOUT_S"], [120.0, 300.0, 600.0], unit="s",
       note="seconds the new release's `launchd.sh probe` may take before the switch; it waits PREFLIGHT_WAIT_S 60 "
            "for its launchd agent, and a timeout fails the deploy before the flip (#1516)"),
    _k("deploy_quiesce_timeout", [f"{Q}:QUIESCE_TIMEOUT_S"], [120.0, 600.0, 1800.0], unit="s",
       note="seconds a deploy due to migrate the store waits, queue paused, for every other job running here to "
            "end; past it the deploy fails not quiesced with the store unmigrated. A deploy starts only when "
            "nothing runs and nothing starts beside it, so the wait is normally 0 (#1795)"),
    _k("deploy_resumes", ["harness/deploy.py:RESUMES"], [1, 0, 2], unit="count",
       note="times settle starts a dead deploy switch again from the stage its record names before it calls the "
            "deploy interrupted (#1753)"),
    _k("deploy_retries", [f"{Q}:RETRIES"], [1, 3, 6],
       note="times the poll queues a sha whose deploy job failed again, each after deploy_retry_after; each failed "
            "attempt restarts the services twice. 2026-11-09: deploy 21 rolled back because the previous release "
            "failed smoke too, and its sha was never tried again (#1672)"),
    _k("deploy_retry_after", [f"{Q}:RETRY_S"], [1800.0, 3600.0, 7200.0], unit="s",
       note="seconds after a deploy job failed before the poll queues the same sha again (#1672)"),
    _k("deploy_smoke_timeout", [f"{Q}:SMOKE_TIMEOUT_S"], [900.0, 1200.0, 1800.0], unit="s",
       note=f"seconds smoke may take in the new release before the switch; {SMOKE} (#1506)"),
    _k("deploy_switch_deadline", [f"{X}:SWITCH_DEADLINE_S"], [1800.0, 3600.0, 7200.0], unit="s",
       note="seconds the whole switch (reinstall, smoke, coherence) may take before it rolls back and alerts; the "
            "rollback gets as long again. Deploy 1's smoke took 41 s on 2026-11-03 and its switch then sat 30+ min "
            "in a reinstall that never started (#1515)"),
    _k("deploy_sync_timeout", [f"{Q}:SYNC_TIMEOUT_S"], [600.0, 1800.0, 3600.0], unit="s",
       note="seconds `uv sync --frozen` may take in a new release; measured 2026-11-03 on the Studio: 0.57 s into an "
            "empty env from a warm uv cache (400 MB); a cold cache downloads every wheel (#1506)"),
    _k("deploy_verify_timeout",[f"{X}:VERIFY_TIMEOUT_S"], [900.0, 1800.0, 3600.0], unit="s",
       note=f"seconds smoke or soh coherence may take on the live system after the switch; {SMOKE} (#1506)"),
    _k("lanprobe_instant_ms", ["harness/lanprobe.py:INSTANT_MS"], [100, 500, 2000],
       note="milliseconds under which a failed LAN connect reads as a denial, not a real no-route, which waits on ARP (#739)"),
]

NOT_GATING = {
    "harness/commands/loop.py:YIELD_POLL_S": "how often a yielded sweep looks whether its deploy is done; it paces "
                                            "the wait, the sweep ceiling bounds it (#1675)",
    "harness/holders.py:_FILEINFO": "byte size of libproc's struct proc_fileinfo, fixed by <sys/proc_info.h> (#1523)",
    "harness/holders.py:_REGIONINFO": "byte size of libproc's struct proc_regioninfo, fixed by <sys/proc_info.h> (#1523)",
    "harness/node_deploy.py:CONNECT_TIMEOUT_S": "how long ssh waits to reach a node; a node that does not answer "
                                                "is marked down and tried again at the next deploy poll (#1692)",
    "harness/node_deploy.py:HEAD_TIMEOUT_S": "how long reading a node's checkout head may take; a timeout marks "
                                             "the node down and the next deploy poll tries again (#1692)",
    "harness/node_deploy.py:WARM_POLL_S": "how often a reinstalled node is asked for /models; it paces the wait, "
                                          "WARM_S bounds it (#1692)",
    "harness/node_state.py:FRESH_S": "how long a node's report is reused before the queue asks again; it paces the "
                                     "ssh reads, and a delegation lease on the node is read live (#1689)",
    "harness/node_state.py:READ_TIMEOUT_S": "how long the ssh reading a node's report may take; a timeout leaves the "
                                            "node's batch work waiting until the next read (#1689)",
    f"{Q}:LAUNCHCTL_TIMEOUT_S": "how long launchctl may take to load the switch's one-shot unit; a timeout fails "
                                "the deploy before the switch and restores the store (#1506)",
    f"{X}:REAP_TIMEOUT_S": "how long a timed-out step's killed process group has to exit; the step already counts "
                           "as timed out and the switch moves on either way (#1515)",
    f"{X}:ALERT_TIMEOUT_S":"how long the deploy alert script may take; the outcome is already recorded (#1506)",
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
    "harness/node_deploy.py:DRAIN_POLL_S": "it paces how often a draining node is asked how many requests it is processing; DRAIN_S bounds the wait (#1815)",
    "harness/node_deploy.py:in_flight->node_state.read(fresh_s)": "a drain asks the node for its in-flight count on every poll; a cached report would show requests already finished (#1815)",
}

NEVER_CUTS = {
    "scripts/launchd.sh:DEPLOY_EVERY_MIN": "how often origin/main is polled; a schedule cuts no work (#1506)",
    f"{Q}:HANDOFF_GRACE_S": "past it a switch that never started is settled interrupted and alerted; the job ends "
                            "either way (#1506)",
    "scripts/launchd.sh:AUDIT_HOURS": "the hour the nightly audit unit starts; a schedule cuts no work (#1087)",
    "scripts/launchd.sh:DISCOVER_HOURS": "the hour the discovery loop starts; its ceiling, not its start, bounds it, "
                                         "a schedule cuts no work (#1087)",
    "harness/lanprobe.py:INSTANT_MS": "classes a failed connect as a denial or no route; the probe ran either way (#739)",
}
