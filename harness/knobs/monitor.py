"""Knobs of the machine monitor monit runs: the Data volume floors, its cycle, and how long a fault holds (#1485)."""
from harness.knobs.base import _k

M = "harness/monitor.py"
FILL = ("KB sohot-2026-10-31-hang-disk-full / sohot-1485-disk-measurements-2026-11-01: on 10-31 the Data volume fell "
        "about 2 GiB per 8 min to 6.9 GiB free and the machine hung; the reboot released about 90 GiB")

KNOBS = [
    _k("monitor_cycle", [f"{M}:CYCLE_S"], [60, 120, 300, 600], unit="s",
       note="seconds between monit's checks; every 'for N cycles' below is its seconds over this (owner, 2026-11-01)"),
    _k("monitor_disk_alert", [f"{M}:DISK_ALERT_GIB"], [25, 50, 100, 150], unit="GiB",
       note="free GiB on the system Data volume below which monit alerts: about 3 h at the 10-31 fill rate (#1485). "
            + FILL),
    _k("monitor_disk_pause", [f"{M}:DISK_PAUSE_GIB"], [10, 25, 40], unit="GiB",
       note="free GiB at which the queue and running evals pause before monit alerts: about 100 min at the 10-31 "
            "fill rate (#1485). " + FILL),
    _k("monitor_du_timeout", [f"{M}:DU_TIMEOUT_S"], [10, 30, 60, 120], unit="s",
       note="seconds the du of the known growers may take on a disk alert; a du of runs alone took over 3 min on "
            "11-01, so a cut grower reads 'not measured' (KB sohot-1485-disk-measurements-2026-11-01)"),
    _k("monitor_memory_warn", [f"{M}:MEMORY_WARN_S"], [300, 600, 1200, 1800], unit="s",
       note="seconds memory pressure holds at warn or worse before monit alerts; on 10-31 the watchdog logged 21 "
            "one-wake warn streaks and 8 of two or more before the hang (KB sohot-1482-2026-10-31-hang-evidence)"),
    _k("monitor_service_down", [f"{M}:SERVICE_DOWN_S"], [300, 600, 1200], unit="s",
       note="seconds a service port stays closed before monit alerts; launchd restarts it meanwhile, so one closed "
            "check is a restart (owner, 2026-11-01; unmeasured)"),
]

NOT_GATING = {
    f"{M}:POST_TIMEOUT_S": "how long the Discord webhook post may take; a timeout is reported in the alert line (#1485)",
    f"{M}:CLI_TIMEOUT_S": "how long monit -t, monit summary, launchctl or the notifier may take; a hang only (#1485)",
    f"{M}:POST_CHARS": "Discord's message length limit; presentation only (#1485)",
}

NEVER_CUTS = {
    f"{M}:CYCLE_S": "how often monit checks; a pace, it cuts no work (#1485)",
}
