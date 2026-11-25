"""Knobs of owner actions (#2116)."""

KNOBS = []

NOT_GATING = {
    "harness/owner_actions.py:ACTION_TIMEOUT_S": "how long the status page waits for an owner verb to return before showing it as timed out; the verbs only queue, hold or flag, and their own clocks decide the work (#2116)",
    "harness/owner_actions.py:TOKEN_TTL_S": "how long a status page's action token is accepted; an expired one is refused and the reloaded page carries a new one (#2116)",
    "harness/owner_actions.py:CONFIRM_TTL_S": "how long the second confirming press of an owner action is accepted after the first; a late one is refused (#2116)",
    "harness/owner_actions.py:BODY_MAX": "the largest owner-action form the status page parses; a larger body is refused like one with no token, and it decides no job, deploy or verdict (#2116)",
    "harness/owner_actions.py:TAIL": "how much of an owner verb's output the status page shows after it ran; it decides nothing (#2116)",
}
