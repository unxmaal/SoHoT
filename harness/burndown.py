"""Issues opened, closed and open per day or week, and open issues by age and label, from gh. #1685."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from harness import ci_history

REPO = ci_history.REPO
#: Every issue, pull requests left out, one compact JSON object a line.
JQ = ".[] | select(.pull_request | not) | {number, created_at, closed_at, state, labels: [.labels[].name]}"
AGES = ((7, "<7d"), (30, "<30d"), (None, "30d+"))
DAY = timedelta(days=1)


def _at(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def closed_at(issue: dict) -> datetime | None:
    """When it closed for good: a reopened issue still open is open, whatever closed_at it carries."""
    return _at(issue.get("closed_at")) if (issue.get("state") or "").upper() == "CLOSED" else None


def is_open(issue: dict, t: datetime) -> bool:
    """Open just before t, so open counts agree with the half-open [start, end) periods."""
    c = closed_at(issue)
    return _at(issue["created_at"]) < t and (c is None or c >= t)


def bounds(now: datetime, periods: int, step_days: int) -> list[datetime]:
    """periods+1 UTC midnights, the last the end of today (or of this ISO week, Monday to Monday)."""
    end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + DAY
    if step_days == 7:
        end += timedelta(days=(7 - end.weekday()) % 7)
    return [end - timedelta(days=step_days * k) for k in range(periods, -1, -1)]


def periods(issues: list[dict], now: datetime, n: int, step_days: int) -> list[dict]:
    """Per period: opened, closed, net, and the open count at its end."""
    edges = bounds(now, n, step_days)
    out = []
    for a, b in zip(edges, edges[1:]):
        opened = sum(a <= _at(i["created_at"]) < b for i in issues)
        closed = sum(a <= c < b for i in issues if (c := closed_at(i)) is not None)
        out.append({"start": a.date().isoformat(), "opened": opened, "closed": closed, "net": opened - closed,
                    "open_at_end": sum(is_open(i, b) for i in issues)})
    return out


def ages(issues: list[dict], now: datetime) -> dict[str, int]:
    out = {name: 0 for _, name in AGES}
    for i in issues:
        if not is_open(i, now):
            continue
        days = (now - _at(i["created_at"])) / DAY
        out[next(name for cap, name in AGES if cap is None or days < cap)] += 1
    return out


def labels(issues: list[dict], now: datetime) -> list[tuple[str, int]]:
    """Open issues per label, most first; an unlabelled one counts under (none)."""
    got: Counter = Counter()
    for i in issues:
        if is_open(i, now):
            got.update(list(i.get("labels") or []) or ["(none)"])
    return sorted(got.items(), key=lambda kv: (-kv[1], kv[0]))


def report(issues: list[dict], now: datetime, n: int, step_days: int) -> dict:
    return {"step_days": step_days, "periods": periods(issues, now, n, step_days), "open": sum(
        is_open(i, now) for i in issues), "ages": ages(issues, now), "labels": labels(issues, now)}


def collect(n: int, step_days: int, gh=None, now: datetime | None = None) -> dict:
    gh = gh or ci_history._gh
    out = gh(["api", "--paginate", f"repos/{REPO}/issues?state=all&per_page=100", "--jq", JQ])
    issues = [json.loads(line) for line in out.splitlines() if line.strip()]
    return report(issues, now or datetime.now(timezone.utc), n, step_days)


def render(got: dict) -> str:
    unit = "week" if got["step_days"] == 7 else "day"
    lines = [f"issues per {unit} (UTC; closed counts an issue that is closed now, at its last close; a reopened "
             "issue still open counts open)", "", f"| {unit} from | opened | closed | net | open at end |",
             "|---|---|---|---|---|"]
    lines += [f"| {p['start']} | {p['opened']} | {p['closed']} | {p['net']:+d} | {p['open_at_end']} |"
              for p in got["periods"]]
    lines += ["", f"open now: {got['open']} (" + ", ".join(f"{k} {v}" for k, v in got["ages"].items()) + ")", "",
              "| label | open |", "|---|---|"]
    lines += [f"| {name} | {k} |" for name, k in got["labels"]]
    return "\n".join(lines)
