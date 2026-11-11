"""Knobs of otel (#1799)."""

KNOBS = []

NOT_GATING = {
    "harness/otel.py:RETRY_AFTER_S": "it is the Retry-After a 503 asks of Claude Code's exporter while the store is ahead; the exporter's own backoff bounds it, and nothing is measured by it (#1799)",
}
