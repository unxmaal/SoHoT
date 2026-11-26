"""Knobs of status page (#2075)."""

KNOBS = []

NOT_GATING = {
    "harness/status_page.py:REFRESH_S": "how stale the read-only status page may be; it decides no job, deploy or verdict (#2075)",
    "harness/status_page.py:ALERT_DAYS": "how far back the status page looks for the last monit alert it displays; it decides nothing (#2075)",
    "harness/status_page.py:SPEND_STALE_S": "when the read-only status page's Discovery tile turns red for no screen or measure; it decides no job, deploy or verdict (#2083)",
    "harness/status_page.py:TIMELINE_S": "how far back the read-only status page's timeline strip draws; it decides nothing (#2078)",
    "harness/status_view.py:BACKUP_STALE_S": "when the read-only status page's Store tile turns amber; it decides no job, deploy or verdict (#2078)",
    "harness/status_page.py:WAITING_SHOWN": "a display cap on the pending jobs the Queue tile lists with buttons; the queue itself is not limited (#2135)",
}
