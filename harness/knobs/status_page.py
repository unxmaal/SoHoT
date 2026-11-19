"""Knobs of status page (#2075)."""

KNOBS = []

NOT_GATING = {
    "harness/status_page.py:REFRESH_S": "how stale the read-only status page may be; it decides no job, deploy or verdict (#2075)",
    "harness/status_page.py:ALERT_DAYS": "how far back the status page looks for the last monit alert it displays; it decides nothing (#2075)",
}
