"""`soh review`: the weekly adversarial review, its precision per dimension, and its kill switch. #1149."""
from __future__ import annotations

import tempfile
from pathlib import Path

from harness.commands.common import emit, err, note


def cmd_review(a) -> int:
    from harness import review
    what = a.review_cmd
    if what in ("off", "on"):
        review.switch(what == "on")
        note(f"the review is {what}")
        emit(off=review.is_off())
        return 0
    if what == "stats":
        return _stats(review)
    if review.is_off():
        note("the review is off (soh review on turns it back on); nothing ran")
        emit(off=True)
        return 0
    dims = tuple(a.dimension) or (("efficiency",) if a.fixture else review.DIMENSIONS)
    unknown = sorted(set(dims) - set(review.DIMENSIONS))
    if unknown:
        return err(f"no such dimension: {', '.join(unknown)}; dimensions are {', '.join(review.DIMENSIONS)}")
    try:
        if a.fixture:
            with tempfile.TemporaryDirectory(prefix="soh-review-fixture-") as tmp:
                source = review.fixture(a.fixture, Path(tmp) / a.fixture)
                r = review.run(source, ref="HEAD", fetch=False, dimensions=dims, file=False, wait=False,
                               say=note)
        else:
            r = review.run(dimensions=dims, file=a.file, say=note, wait_h=a.wait_h)
    except (RuntimeError, OSError) as exc:
        return err(str(exc))
    _show(r)
    emit(**r)
    if a.fixture:
        return 0 if r.get("known_answer") in ("found", "clean") else 1
    return 0


def _show(r: dict) -> None:
    if r.get("skipped"):
        note(f"not run: {r['skipped']}")
        return
    note(f"review of {r.get('sha', '')[:12]} ({r['source']}, {r['mode']})"
         + (f", changes since {r['since'][:12]}" if r.get("since") else ""))
    for dim, why in sorted(r.get("switched_off", {}).items()):
        note(f"  {dim}: switched off, {why}")
    for dim, why in sorted(r.get("errors", {}).items()):
        note(f"  {dim}: no findings, the call went wrong: {why}")
    for c in r["candidates"]:
        issue = f" #{c['issue']}" if c.get("issue") else ""
        note(f"  {c['fate']:12}{issue} [{c['dimension']}] {c.get('title', '')}"
             + (f" ({c.get('file')}:{c.get('line')})" if c.get("file") else "")
             + (f": {c['why']}" if c["why"] and c["fate"] not in ("filed", "would file") else ""))
        if c["fate"] == "would file":
            note(f"\n    {c['issue_title']}\n" + "\n".join(f"    {line}" for line in c["body"].splitlines()) + "\n")
    note(f"tokens {r['tokens']:,} over {len(r['calls'])} claude -p calls"
         + (f"; limits {', '.join(r['limits'])}" if r["limits"] else ""))
    if r.get("known_answer"):
        note(f"known answer: {r['known_answer']}")
    note(f"receipt {r['path']}")


def _stats(review) -> int:
    s = review.stats()
    if not s:
        note("no review-bot issue has been filed yet")
    for dim, row in sorted(s.items()):
        p = "-" if row["precision"] is None else f"{row['precision']:.2f}"
        note(f"{dim:11} filed {row['filed']:3}  completed {row['completed']:3}  not planned {row['not_planned']:3}  "
             f"open {row['open']:3}  precision {p}  over {row['weeks']} weeks" + ("  SWITCHED OFF" if row["off"] else ""))
    emit(dimensions=s)
    return 0
