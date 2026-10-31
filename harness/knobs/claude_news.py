"""Knobs of `soh claude-news` and its weekly launchd unit (#866)."""
from harness.knobs.base import _k

KNOBS = [
    _k("claude_news_hour", ["scripts/launchd.sh:CLAUDE_NEWS_HOUR"], [9, 12],
       note="local hour the Claude Code changelog digest runs on its weekday (#866)"),
    _k("claude_news_weekday", ["scripts/launchd.sh:CLAUDE_NEWS_WEEKDAY"], [1, 5],
       note="launchd weekday (0 or 7 Sunday, 1 Monday) the Claude Code changelog digest runs (#866)"),
]

NOT_GATING = {
    "harness/claude_news.py:FETCH_TIMEOUT_S": "how long fetching the Claude Code CHANGELOG.md may take; a slow "
                                              "fetch fails the run and records nothing, so the next run covers it (#866)",
    "harness/claude_news.py:VERSION_TIMEOUT_S": "how long `claude --version` may take; a slow one leaves the "
                                                "installed version unknown in the setup summary (#866)",
}

NEVER_CUTS = {
    "scripts/launchd.sh:CLAUDE_NEWS_HOUR": "the hour the weekly digest starts; a schedule cuts no work (#1087)",
    "scripts/launchd.sh:CLAUDE_NEWS_WEEKDAY": "the day the weekly digest starts; a schedule cuts no work (#1087)",
}
