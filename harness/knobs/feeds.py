"""Knobs of the feeds and registries the discover sweep reads (#704)."""
from harness.knobs.base import _k

KNOBS = [
    _k("feed_unreachable_retries", ["harness/feeds.py:UNREACHABLE_RETRIES"], [0, 1, 2, 4],
       note="retries for a feed host that did not answer at all; a 429 gets feeds.RETRIES (#704)"),
    _k("papers_description_chars", ["harness/papers.py:DESCRIPTION_CHARS", "harness/posts.py:DESCRIPTION_CHARS"], [300, 600, 1500],
       note="characters of a paper's title and abstract kept as its description, which lanes.technique_route reads (#576, #631)"),
    _k("ratelimit_attempts", ["harness/ratelimit.py:ATTEMPTS"], [2, 3, 5, 8],
       note="GETs an upstream answering 429 gets before the caller defers the rest of its batch (#630, #1085)"),
    _k("triage_draft_tokens", ["harness/technique_triage.py:DRAFT_TOKENS"], [800, 1500, 3000],
       note="reply budget of one triage draft, a JSON template of a few steps (#993)"),
    _k("triage_per_run", ["harness/technique_triage.py:PER_RUN"], [0, 12, 40, 80, 160],
       note="drafts one technique triage makes a night: about 530 triageable techniques drain in a week at 80, "
            "and a warm draft measured 0.5-0.9 s on 2026-10-31, a canary a few calls more (#993, #1476)"),
]
