"""Knobs of the deploy guards in scripts/launchd.sh (#870, #1000, #1058)."""
from harness.knobs.base import _k

M = "harness/deploy_guard.py"
S = "harness/sweep_guard.py"

KNOBS = [
    _k("lanprobe_instant_ms", ["harness/lanprobe.py:INSTANT_MS"], [100, 500, 2000],
       note="milliseconds under which a failed LAN connect reads as a denial, not a real no-route, which waits on ARP (#739)"),
]

NOT_GATING = {
    "scripts/launchd.sh:LH_DEFER_WAIT_S": "how long install waits for a live periodic run to end before reloading "
                                          "it; at the deadline the unit stays deferred and install fails (#1058)",
    f"{M}:GH_TIMEOUT_S": "how long gh may take to say whether check-macos passed; a timeout refuses the deploy (#870)",
    f"{S}:PS_TIMEOUT_S": "how long ps may take to name a pid's command; a slow ps leaves the pid counted as a "
                         "sweep, so the deploy refuses rather than guesses (#1000)",
    f"{S}:STOP_GRACE_S": "how long an overridden sweep has between TERM and KILL; the same role as "
                         "watchdog.STOP_GRACE_S (#1000)",
}

NEVER_CUTS = {
    "harness/lanprobe.py:INSTANT_MS": "classes a failed connect as a denial or no route; the probe ran either way (#739)",
}
