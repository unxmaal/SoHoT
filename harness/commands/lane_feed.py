"""`soh lane-feed <lane>`: one lane's findings as the versioned document the MCP and the reports branch carry. #1200."""
from __future__ import annotations

import json

from harness.commands.common import err


def add_parser(sub) -> None:
    p = sub.add_parser("lane-feed", help="one lane's served model, candidates and their verdicts, exams, settled "
                       "knobs and events, read-only; --since N lists only the events after id N")
    p.add_argument("lane", help="the lane, e.g. video")
    p.add_argument("--since", type=int, default=None, help="only events whose id is greater than this cursor")
    p.add_argument("--store", default="", help="a discovery.db to read (default: this home's, opened read-only)")
    p.set_defaults(func=cmd_lane_feed)


def cmd_lane_feed(a) -> int:
    from harness import lane_feed
    try:
        doc = lane_feed.read(a.lane, a.since, a.store)
    except (lane_feed.UnknownLane, FileNotFoundError) as exc:
        return err(str(exc))
    if getattr(a, "json", False):
        print(json.dumps(doc, indent=1, sort_keys=True))
        return 0
    s = doc["served"]
    print(f"{doc['lane']['name']}: serves {s['serves'] or '--'}"
          + (f", adopted {s['adopted_how']} {s['adopted_at'][:10]}" if s["adopted"] else ""))
    print(f"  {doc['lane']['cases']} case(s), digest {doc['lane']['cases_digest'] or '--'}")
    for c in doc["candidates"]:
        print(f"  {c['status']:<9} {c['candidate']}" + (f": {c['reason']}" if c["reason"] else ""))
    for k in doc["knobs"]:
        print(f"  knob {k['knob']} on {k['candidate']}: {k['outcome']} {k['chosen'] if k['chosen'] is not None else ''}")
    print(f"  {len(doc['events'])} event(s) after {doc['since']}; cursor {doc['cursor']}")
    return 0
