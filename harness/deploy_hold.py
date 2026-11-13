"""The audit checks a failed deploy step names as FAIL, for its record (#1805); the poll retries no rolled-back sha (#1913)."""
from __future__ import annotations

import re

# Stdlib only at import: deploy_switch runs it under the base interpreter with -I (#1610).

#: An audit check's failing line as live_audit.report_text prints it; smoke's `FAIL  x` lines do not match.
FAIL_LINE = re.compile(r"^  FAIL (\w+)(?::\s*(.*))?$")
VERDICT = re.compile(r"\bverdict (\d+)\b")


def failed(text: str) -> dict:
    """{check: [verdict ids its FAIL lines name]} for every audit check that failed in text."""
    out: dict = {}
    for line in text.splitlines():
        m = FAIL_LINE.match(line)
        if m:
            ids = out.setdefault(m.group(1), [])
            ids += [int(v) for v in VERDICT.findall(m.group(2) or "") if int(v) not in ids]
    return out
