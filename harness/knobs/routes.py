"""Knobs of the request-routing trial arms (#1338)."""
from harness.knobs.base import _k

KNOBS = [
    _k("route_delegation_poll", ["harness/routes.py:DELEGATION_POLL_S"], [15.0, 60.0, 300.0], unit="s",
       note="seconds between the gateway's reads of closed delegation outcomes; outcomes close hourly (#1158, #1338)"),
    _k("route_quality_weight", ["harness/routes.py:QUALITY_WEIGHT"], [0.7, 0.9, 1.0], unit="share",
       note="share of the adaptive arm's score that is the sampled pass rate, the rest cost; LiteLLM's default 0.7 "
            "leaves a cloud pick needing a 0.43 higher sampled pass rate even at no tier distance (#1338)"),
    _k("route_remembered_calls", ["harness/routes.py:REMEMBERED_CALLS"], [1024, 4096, 16384], unit="calls",
       note="adaptive-arm calls the gateway holds awaiting a verdict; a lane exam is under 700 cases (#1338)"),
    _k("route_tier_penalty", ["harness/routes.py:TIER_PENALTY"], [0.0, 0.05, 0.5], unit="score",
       note="score per tier step from the classified tier; LiteLLM's 0.5 outweighs any verdict with one model per "
            "tier, so the arm could never leave the classified tier's model (#1338, issue comment)"),
]

NEVER_CUTS = {
    "harness/routes.py:QUALITY_WEIGHT": "weighs the adaptive arm's pick; every request is still answered (#1338)",
    "harness/routes.py:TIER_PENALTY": "weighs the adaptive arm's pick; every request is still answered (#1338)",
    "harness/routes.py:DELEGATION_POLL_S": "delays reading closed outcomes to the next poll; none is skipped (#1338)",
}
