"""Knobs of delegation outcomes: expiry, the span match, and the delegations launchd unit (#1158)."""
from harness.knobs.base import _k

KNOBS = [
    _k("delegation_every", ["scripts/launchd.sh:DELEGATIONS_EVERY_MIN"], [15, 60],
       note="minutes between runs of the delegations unit, which closes pending outcomes (#1158)"),
    _k("delegation_expiry", ["harness/delegations.py:EXPIRY_H"], [6.0, 24.0, 72.0],
       note="hours after a delegation with no evidence before its outcome is recorded unknown (#1158)"),
    _k("delegation_span_chars", ["harness/delegations.py:SPAN_CHARS"], [20, 30, 60],
       note="shortest answer line, whitespace collapsed, looked for in a later tool input (#1158)"),
    _k("delegation_span_share", ["harness/delegations.py:SPAN_SHARE"], [0.1, 0.25, 0.5],
       note="share of the answer's own lines a later tool input must hold to count it accepted (#1158)"),
]
