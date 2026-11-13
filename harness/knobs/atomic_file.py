"""Knobs of atomic file (#1905)."""

KNOBS = []

NOT_GATING = {
    "harness/atomic_file.py:REPLACE_TIMEOUT_S": "it bounds retries of a rename Windows refuses while another writer or reader holds the target; the write lands or raises, and no measured outcome depends on how long it waited (#1905)",
}
