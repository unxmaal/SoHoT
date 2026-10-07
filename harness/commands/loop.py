"""`soh discover --loop`: the tiers chained, the queue they share, and the spend that settles them."""
from __future__ import annotations

from harness import lanes
from harness.commands import discover as discover_cmd
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd


def _queueable(store, want: str = "") -> tuple[list[dict], int]:
    """The waiting candidates in scope, and how many there are.

    SCOPE FIRST, THEN LIMIT. cmd_queue used to fetch `top * 4` rows and filter
    those, so `--lane` did not scope the queue: it sampled the backlog in
    whatever order the store returned it and kept whatever matched. At the
    default --top 25 the sample is 100 of 114 and the defect is invisible; at
    --top 2 it is 8, and the image lane reported empty while holding five
    candidates. A narrow budget is exactly when the scope matters most, and it
    was where the sampling bit hardest. Issue #209.

    The returned count is the in-scope total, because a scoped queue printing
    "5 of 114 waiting" answers a different question with its denominator than
    with its numerator.
    """
    from harness import rank
    from harness import memory_store as ms

    rows = ms.judgeable(store, limit=1_000_000)
    if want:
        rows = [r for r in rows if lanes.serves(rank.lane_of(r), want)]
    return rows, len(rows)


#: The loop, in order: (label, the attribute cmd_discover dispatches on, does
#: it need --run). Sweeping reads feeds and the GitHub API and takes about a
#: minute, which is the "find what exists" step and runs either way. INSPECT
#: CLONES SOURCE, measured at over ten minutes across a full queue, so it is
#: gated with the rest: a dry run that takes ten minutes is not a dry run.
LOOP_STEPS = (("sweep", "sweep", False),
              ("inspect", "inspect", True),
              ("queue", "queue", False))

#: How many queued candidates the loop's inspect step sizes, which is NOT
#: `--top`. Those are two different questions and tying them together is what
#: made the loop inert: `--top` is how many candidates to carry the whole way
#: and spend disk on, so `--top 1` is a sensible thing to ask for, while
#: inspecting one row of a 46-row queue leaves the other 45 unsized and the
#: fetch tier refuses every one of them. Inspection downloads nothing.
LOOP_INSPECT = 50


def _in_fetch_order(store, work_items):
    """Reorder inspect's work to match the order the fetch tier will read.

    Returns the same items, never fewer: a name the fetch queue does not carry
    is still worth inspecting, it simply goes last.
    """
    from harness import fetching
    try:
        ranked = fetching.in_rank_order(
            fetching.queued(store, needs_lane=False), store)
    except Exception:  # noqa: BLE001
        # An ordering is an optimisation. Failing to compute one must not
        # stop the tier that does the actual work.
        return work_items
    place = {r["name"]: i for i, r in enumerate(ranked)}
    return sorted(work_items, key=lambda it: place.get(it[0], len(place)))


def _report_loop(a) -> int:
    """Every step from a sweep to an adopted winner. Issue #201.

    SAYS WHAT IT WOULD DO AND STOPS unless --run. Fetching weights and running
    a lane are the two operations that spend gigabytes and minutes, and a loop
    that starts doing either because something ranked well is how a laptop ends
    up unusable overnight.
    """
    import argparse as _ap

    from harness import adopt, rank
    from harness import memory_store as ms

    run = bool(getattr(a, "run", False))
    rc = 0
    for label, attr, needs_run in LOOP_STEPS:
        if needs_run and not run:
            print(f"\n=== {label} (skipped; --run) ===")
            continue
        print(f"\n=== {label} ===")
        flags = {f: f == attr for _, f, _ in LOOP_STEPS}
        extra = {}
        if attr == "inspect":
            # INSPECT WHAT THE SWEEP FOUND, not the crowd. cmd_inspect's own
            # comment calls --from-store "the rung the ladder was missing",
            # and the loop never passed it, so the loop inspected new GitHub
            # sightings while the QUEUE stayed unsized. Every one of 46 queued
            # candidates was then skipped by fetch with "no measured size;
            # inspect it first", immediately after the loop's own inspect step
            # had run. Two tiers in one command, reading different sources.
            extra = {"from_store": True, "top": LOOP_INSPECT}
        sub = _ap.Namespace(**{**vars(a), **flags, **extra, "loop": False})
        rc = discover_cmd.cmd_discover(sub) or rc

    want = (getattr(a, "lane", "") or "").strip().lower()
    store = ms.connect()
    try:
        rows, _ = _queueable(store, want)
        if want:
            print(f"\n(scoped to the {want} lane: {len(rows)} candidate(s))")
        short = rank.wanted(rows)
        if short:
            print(f"\n=== lanes wanted ===")
            print(f"{len(short)} candidate(s) recur and no lane can test them. "
                  f"A lane is a decision for a person, so they are reported "
                  f"rather than ranked or invented:")
            for row in short[:10]:
                print(f"  {row.get('times', 0)}x  {row['name']}")
        stuck = rank.runnerless(rows)
        if stuck:
            print(f"\n=== runners wanted ===")
            print(f"{len(stuck)} candidate(s) have a lane and no runner that "
                  f"can load them. An engine entry is a decision for a person "
                  f"-- a guessed one is a binary that refuses the model "
                  f"several seconds into loading:")
            for row in stuck[:10]:
                print(f"  {row.get('lane', ''):8} {row['name']}\n"
                      f"           {row['why_not']}")
        print(f"\n=== adopted ===")
        current = adopt.current(store)
        if current:
            for lane, row in sorted(current.items()):
                print(f"  {lane:8} {row['spec']}  ({row['how']})")
        else:
            print("  nothing adopted yet; every lane serves its typed constant")
    finally:
        store.close()

    if not run:
        print("\ninspect, fetch, screen and measure not run. Add --run to "
              "spend the disk and the minutes.")
        return rc
    return _spend_and_settle(a, rc)


def _spend_and_settle(a, rc: int) -> int:
    """_loop_spend, then leave only lane defaults resident in the router. #444."""
    from harness import router
    try:
        rc = _loop_spend(a, rc)
    finally:
        router.settle("the discovery loop is done")
    _publish_if_enabled()
    return rc


def _publish_if_enabled() -> str:
    """Publish this machine's report when its publish switch is on. #432."""
    from harness import publish
    if not publish.enabled():
        return ""
    print("\n=== publish ===")
    try:
        path = publish.publish_here()
    except Exception as exc:  # noqa: BLE001
        print(f"  not published: {exc}")
        return ""
    print(f"  wrote {path} on the {publish.BRANCH} branch")
    return path


def _loop_spend(a, rc: int) -> int:
    """Fetch, screen, measure and adopt, ONE CANDIDATE AT A TIME.

    Serial by construction, not by accident. An eval sweeping aliases took this
    machine down by loading a 16 GiB model while a 7.8 GiB one was still
    resident (RULE #193). The budget is a ceiling on what this invocation will
    download, and `--top` a ceiling on how many candidates it will carry the
    whole way.
    """
    import argparse as _ap

    from harness import adopt, fetching, screen
    from harness import memory_store as ms

    from harness import disk

    print("\n=== retests ===")
    _reopen_retests()

    # After the retests, so a reopened candidate's weights are queued, not swept.
    print("\n=== disk ===")
    disk.sweep()

    top = int(getattr(a, "top", 3) or 3)
    budget = float(getattr(a, "budget_gib", 20.0) or 20.0)

    want = (getattr(a, "lane", "") or "").strip().lower()
    if want:
        print(f"\n(spending only on the {want} lane)")
    print(f"\n=== fetch (up to {top}, budget {budget:g} GiB) ===")
    backlog = screen_cmd.screenable_backlog(want)
    if len(backlog) >= top:
        print(f"  skipped: {len(backlog)} candidate(s) already on disk wait "
              f"for a screen, and this run screens {top}")
    else:
        sub = _ap.Namespace(**{**vars(a), "loop": False, "run": True,
                               "limit": top, "json": False})
        rc = screen_cmd.cmd_fetch(sub) or rc

    print(f"\n=== screen ===")
    sub = _ap.Namespace(**{**vars(a), "loop": False, "screen": True,
                           "run": True, "limit": top, "json": False})
    rc = discover_cmd.cmd_discover(sub) or rc

    print(f"\n=== measure and adopt ===")
    store = ms.connect()
    try:
        fresh = measure_cmd.measurable(store, top, want)
    finally:
        store.close()
    if not fresh:
        print("  nothing survived the screen, so there is nothing to measure. "
              "A screen that rejects everything is the tier doing its job.")
        return rc
    for row in fresh:
        rc = measure_cmd._measure_and_adopt(a, row) or rc
    return rc


def _reopen_retests(now: float | None = None) -> list[str]:
    """Reopen screen and measure rejections whose retest is due. #431."""
    from harness import memory_store as ms
    store = ms.connect()
    try:
        names = ms.reopen_due_retests(store, now)
    finally:
        store.close()
    print(f"  reopened {len(names)} rejection(s) for a retest")
    for n in names:
        print(f"    {n}")
    return names
