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

#: The spend's steps, after LOOP_STEPS, for the heartbeat's step N of M. #251.
SPEND_STEPS = ("retests", "reverify", "knob sweeps", "disk", "fetch", "screen", "measure")
LOOP_TOTAL = len(LOOP_STEPS) + len(SPEND_STEPS)


def _beat(tier: str, **kw) -> None:
    from harness import heartbeat
    names = [label for label, _, _ in LOOP_STEPS] + list(SPEND_STEPS)
    heartbeat.beat(tier, step=names.index(tier) + 1, **kw)


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


def _lanes_wanted_lines(rows, ceiling_gib: float, top: int = 10) -> list[str]:
    """The `lanes wanted` section: laneless models by task, evidence only. #558."""
    from harness import rank
    groups = rank.wanted_groups(rows, ceiling_gib=ceiling_gib)
    if not groups:
        return []
    n = sum(len(g["models"]) for g in groups)
    out = ["\n=== lanes wanted ===",
           f"{n} laneless model(s) in {len(groups)} task group(s). A lane is a "
           f"decision for a person; this orders the evidence and decides nothing.",
           f"  {'task':28} {'models':>6} {'publishers':>10} {'sightings':>9}  "
           f"{'fits':7} measurable"]
    for g in groups[:top]:
        metric = f"yes ({g['metric']})" if g["metric"] else "unknown"
        out.append(f"  {g['task']:28} {len(g['models']):>6} {len(g['publishers']):>10} "
                   f"{g['sightings']:>9}  {g['fits']:7} {metric}")
        out.append(f"      e.g. {', '.join(g['models'][:3])}")
        out.append(f"      used here? would anything on this machine act on "
                   f"a {g['task']} answer?")
    if len(groups) > top:
        out.append(f"  ... and {len(groups) - top} more group(s)")
    return out


def _techniques_wanted_lines(rows, want: str = "", per_lane: int = 5) -> list[str]:
    """The `techniques wanted` section: per lane, the papers and repos naming a method. #576."""
    from harness import rank
    groups = rank.techniques_wanted(rows, want)
    laneless = 0 if want else rank.techniques_laneless(rows)
    if not groups and not laneless:
        return []
    n = sum(len(g["techniques"]) for g in groups)
    out = ["\n=== techniques wanted ===",
           f"{n} technique(s) in {len(groups)} lane(s). Implementing a method is a "
           f"job for a person or an agent; this lists the evidence and decides nothing."]
    for g in groups:
        out.append(f"  {g['lane']}  {len(g['techniques'])} technique(s), "
                   f"{g['sightings']} sighting(s)")
        for t in g["techniques"][:per_lane]:
            out.append(f"    {int(t.get('times') or 0)}x  {t.get('title') or t['name']}")
            if t.get("url"):
                out.append(f"        {t['url']}")
        if len(g["techniques"]) > per_lane:
            out.append(f"    ... and {len(g['techniques']) - per_lane} more")
    if want:
        return out
    from harness import lanes
    unlaned = rank.techniques_unlaned(rows)
    for bucket, why in ((lanes.SERVING, "not a lane: a serving method"),
                        (lanes.GENERAL, "not a lane: a general text-model method")):
        if unlaned[bucket]:
            out.append(f"  {bucket}  {len(unlaned[bucket])} technique(s), {why}")
            out += _technique_titles(unlaned[bucket], per_lane)
    if unlaned[""]:
        out.append(f"  {len(unlaned[''])} technique(s) name no lane the prose routing knows:")
        out += _technique_titles(unlaned[""], per_lane)
    return out


def _technique_titles(rows, per_lane: int) -> list[str]:
    out = [f"    {int(t.get('times') or 0)}x  {t.get('title') or t['name']}" for t in rows[:per_lane]]
    if len(rows) > per_lane:
        out.append(f"    ... and {len(rows) - per_lane} more")
    return out


def _report_loop(a) -> int:
    """The loop under a heartbeat that says where it is, finished however it ends. #251."""
    from harness import heartbeat
    run = bool(getattr(a, "run", False))
    heartbeat.start(lane=(getattr(a, "lane", "") or "").strip().lower(),
                    total=LOOP_TOTAL if run else len(LOOP_STEPS))
    try:
        rc = _run_loop(a)
    except BaseException as exc:
        heartbeat.finish(None, error=f"{type(exc).__name__}: {exc}")
        raise
    heartbeat.finish(rc)
    return rc


def _run_loop(a) -> int:
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
    failed: list[str] = []
    for label, attr, needs_run in LOOP_STEPS:
        if needs_run and not run:
            print(f"\n=== {label} (skipped; --run) ===")
            continue
        print(f"\n=== {label} ===")
        _beat(label)
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
        rc = _step(label, discover_cmd.cmd_discover(sub), failed) or rc

    want = (getattr(a, "lane", "") or "").strip().lower()
    store = ms.connect()
    try:
        for line in _methods_lines(_cross_methods(store, want)):
            print(line)
        rows, _ = _queueable(store, want)
        if want:
            print(f"\n(scoped to the {want} lane: {len(rows)} candidate(s))")
        for line in _lanes_wanted_lines(rows, ms.this_machine()["ceiling_gb"]):
            print(line)
        tools = rank.tools_wanted(rows)
        if tools:
            print(f"\n=== engines/tools wanted ===")
            print(f"{len(tools)} tooling repo(s) recur with no model task. An "
                  f"engine entry is a decision for a person, not a lane:")
            for row in tools[:10]:
                print(f"  {row.get('times', 0)}x  {row['name']}")
        for line in _techniques_wanted_lines(ms.techniques(store), want):
            print(line)
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
        _report_binding(store)
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
        return _why_nonzero(rc, failed)
    return _why_nonzero(_spend_and_settle(a, rc, failed), failed)


def _step(label: str, got, failed: list) -> int:
    """A step's exit status, with its label noted when it is not 0. #601."""
    if got:
        failed.append(label)
    return got or 0


def _why_nonzero(rc: int, failed: list) -> int:
    """Say which steps made the loop exit nonzero, after the publish line hides them. #601."""
    if rc:
        from harness.commands.common import err
        err(f"\nloop exit {rc}: {', '.join(failed) or 'a step'} reported a failure (see above)")
    return rc


def _spend_and_settle(a, rc: int, failed: list | None = None) -> int:
    """_loop_spend, then leave only lane defaults resident in the router. #444."""
    from harness import router
    try:
        rc = _loop_spend(a, rc, failed if failed is not None else [])
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


def _loop_spend(a, rc: int, failed: list | None = None) -> int:
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
    failed = failed if failed is not None else []

    print("\n=== retests ===")
    _beat("retests")
    _reopen_retests()

    print("\n=== reverify ===")
    _beat("reverify")
    _reverify()

    print("\n=== knob sweeps ===")
    _beat("knob sweeps")
    _sweeps()

    # After the retests, so a reopened candidate's weights are queued, not swept.
    print("\n=== disk ===")
    _beat("disk")
    disk.sweep()

    top = int(getattr(a, "top", 3) or 3)
    budget = float(getattr(a, "budget_gib", 20.0) or 20.0)

    want = (getattr(a, "lane", "") or "").strip().lower()
    if want:
        print(f"\n(spending only on the {want} lane)")
    print(f"\n=== fetch (up to {top}, budget {budget:g} GiB) ===")
    _beat("fetch")
    backlog = screen_cmd.screenable_backlog(want)
    if len(backlog) >= top:
        print(f"  skipped: {len(backlog)} candidate(s) already on disk wait "
              f"for a screen, and this run screens {top}")
    else:
        sub = _ap.Namespace(**{**vars(a), "loop": False, "run": True,
                               "limit": top, "json": False})
        rc = _step("fetch", screen_cmd.cmd_fetch(sub), failed) or rc

    print(f"\n=== screen ===")
    _beat("screen")
    sub = _ap.Namespace(**{**vars(a), "loop": False, "screen": True,
                           "run": True, "limit": top, "json": False})
    rc = _step("screen", discover_cmd.cmd_discover(sub), failed) or rc

    print(f"\n=== measure and adopt ===")
    _beat("measure")
    store = ms.connect()
    try:
        fresh = measure_cmd.measurable(store, top, want)
    finally:
        store.close()
    if not fresh:
        print("  nothing survived the screen, so there is nothing to measure. "
              "A screen that rejects everything is the tier doing its job.")
        return rc
    for i, row in enumerate(fresh, 1):
        _beat("measure", candidate=row.get("name", ""), item=i, items=len(fresh))
        rc = _step(f"measure {row.get('name', '')}".strip(),
                   measure_cmd._measure_and_adopt(a, row), failed) or rc
    return rc


def _reverify() -> dict:
    """Queue re-runs of served models whose triggers fired; never runs one inline. #480."""
    from harness import reverify
    from harness import memory_store as ms
    from harness.commands import reverify as reverify_cmd
    store = ms.connect()
    try:
        got = reverify.check(store)
    finally:
        store.close()
    reverify_cmd.report(got)
    return got


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


def _cross_methods(store, want: str = "") -> list[tuple[str, str, bool]]:
    """Queue each registered method over each lane's incumbent; (lane, spec, newly queued). #576.
    A known crossing is left alone. Interim until proposals carry a category: kind `method`."""
    from harness import adopt, methods, reasons, winners
    from harness import memory_store as ms
    typed = winners.typed()

    def incumbent_of(lane):
        return adopt.default_for(lane, typed.get(lane, ""), conn=store)

    out = []
    for lane in lanes.ALL:
        if (want and lane != lanes.canonical(want)) or lanes.parked(lane)[0]:
            continue
        for spec in methods.crossings(lane, incumbent_of):
            known = store.execute("SELECT 1 FROM proposals WHERE name = ?",
                                  (spec,)).fetchone()
            if not known:
                parsed = methods.parse(spec)
                ms.record(store, ms.Seen(
                    name=spec, source=methods.CROSSING_SOURCE, kind=methods.CROSSING_KIND,
                    lane=lane, resolved=spec,
                    why=f"{parsed.method.name} over the incumbent {parsed.base}",
                    description=parsed.method.note))
                ms.decide(store, spec, "queued", tier=ms.INSPECT,
                          detail=f"a registered method over the {lane} lane's incumbent",
                          reason=reasons.CANDIDATE)
            out.append((lane, spec, not known))
    return out


def _methods_lines(crossed) -> list[str]:
    """The `methods` section: which crossings were queued this run and which were known."""
    if not crossed:
        return []
    out = ["\n=== methods ===",
           "each registered method over each lane's incumbent, queued like any candidate:"]
    for lane, spec, new in crossed:
        out.append(f"  {'queued' if new else 'known ':6}  {lane:8} {spec}")
    return out


def _report_binding(store, now: float | None = None) -> None:
    """The knobs whose limits this machine's recent runs keep hitting. #636."""
    from harness import binding, runs
    print("\n=== binding knobs ===")
    print(binding.render(binding.count(store, now=now, machines=runs.here(store))))


def _sweeps() -> dict:
    """Settle finished knob sweeps and queue one per binding knob not yet swept here. #636."""
    from harness import memory_store as ms, sweeps
    store = ms.connect()
    try:
        got = sweeps.check(store)
    finally:
        store.close()
    print(sweeps.render(got))
    return got
