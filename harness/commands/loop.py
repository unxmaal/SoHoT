"""`soh discover --loop`: the tiers chained, the queue they share, and the spend that settles them."""
from __future__ import annotations

from harness import lanes, methods, repo_gate
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
        rows = [r for r in rows if methods.serves(r["name"], rank.lane_of(r), want)]
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


#: The store lease one discover loop holds, so machines sharing a store never sweep together. #703.
LEASE = "discover-loop"
#: How long a loop's lease outlives a holder that vanished without releasing it. #703.
LEASE_S = 24 * 3600.0


def _run_loop(a) -> int:
    """The loop under the store lease: a second machine's loop refuses rather than races. #703."""
    import sys

    from harness import lease
    from harness import memory_store as ms
    from harness import workqueue as wq

    if not getattr(a, "run", False):
        # A dry run spends nothing, so it needs no lease and never refuses.
        return _run_loop_held(a)
    conn = ms.connect()
    try:
        who = lease.owner(conn)
        held = lease.take(conn, LEASE, who, LEASE_S, alive=wq.alive)
    finally:
        conn.close()
    if held:
        print(f"another discover loop holds the store lease (machine {held.get('machine_id')}, "
              f"pid {held.get('pid')}); not starting a second", file=sys.stderr)
        return 1

    def keep() -> bool:
        conn = ms.connect()
        try:
            return lease.renew(conn, LEASE, who, LEASE_S)
        finally:
            conn.close()

    try:
        return _run_loop_held(a, keep)
    finally:
        conn = ms.connect()
        try:
            lease.release(conn, LEASE, who)
        finally:
            conn.close()


def _run_loop_held(a, keep=None) -> int:
    """Every step from a sweep to an adopted winner. Issue #201.

    SAYS WHAT IT WOULD DO AND STOPS unless --run. Fetching weights and running
    a lane are the two operations that spend gigabytes and minutes, and a loop
    that starts doing either because something ranked well is how a laptop ends
    up unusable overnight.
    """
    import argparse as _ap
    import sys

    from harness import adopt, ceiling, fetching, power, rank
    from harness import memory_store as ms

    run = bool(getattr(a, "run", False))
    sweep = ceiling.Sweep(float(getattr(a, "ceiling_h", None) or power.SWEEP_CEILING_H) * 3600)
    rc = 0
    failed: list[str] = []
    for label, attr, needs_run in LOOP_STEPS:
        if needs_run and not run:
            print(f"\n=== {label} (skipped; --run) ===")
            continue
        if keep is not None and not keep():
            print(f"the discover loop lost its store lease before {label}; stopping so two "
                  f"machines never sweep together", file=sys.stderr)
            return 1
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
            for repair, args in ((_reopen_stale_too_big, ()), (_reopen_unranked, ()),
                                 (_reopen_upstream_committed, ()), (_reread_runtime_declines, (a,)),
                                 (_move_past_screen, ()), (_reopen_revisitable, ()),
                                 (_rederive_attachments, ()), (_relane_vision, ())):
                rc = _repair(label, repair, args, failed) or rc
        sub = _ap.Namespace(**{**vars(a), **flags, **extra, "loop": False})
        rc = _step(label, discover_cmd.cmd_discover(sub), failed) or rc

    want = (getattr(a, "lane", "") or "").strip().lower()
    store = ms.connect()
    try:
        for line in _triage_lines(store, want, bool(getattr(a, "run", False))):
            print(line)
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
        named = {r["name"] for r in stuck}
        stuck += [r for r in fetching.format_wanted(store, want) if r["name"] not in named]
        named = {r["name"] for r in stuck}
        stuck += [r for r in ms.runner_waits(store, want) if r["name"] not in named]
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
    return _why_nonzero(_spend_and_settle(a, rc, failed, sweep), failed)


def _step(label: str, got, failed: list) -> int:
    """A step's exit status, with its label noted when it is not 0. #601."""
    if got:
        failed.append(label)
    return got or 0


def _repair(label: str, repair, args, failed: list) -> int:
    """Run one pre-step repair; a crash is a failed step under its label, never the end of the sweep. #974."""
    import traceback
    try:
        repair(*args)
    except Exception as exc:
        traceback.print_exc()
        print(f"  {label}: {repair.__name__} failed ({type(exc).__name__}: {exc}); going on", flush=True)
        return _step(f"{label} ({repair.__name__})", 1, failed)
    return 0


def _why_nonzero(rc: int, failed: list) -> int:
    """Say which steps made the loop exit nonzero, after the publish line hides them. #601."""
    if rc:
        from harness.commands.common import err
        err(f"\nloop exit {rc}: {', '.join(failed) or 'a step'} reported a failure (see above)")
    return rc


def _spend_and_settle(a, rc: int, failed: list | None = None, sweep=None) -> int:
    """_loop_spend, then leave only lane defaults resident in the router. #444."""
    from harness import router
    try:
        rc = _loop_spend(a, rc, failed if failed is not None else [], sweep)
    finally:
        router.settle("the discovery loop is done")
        if sweep is not None:
            print("\n".join(sweep.summary()))
            from harness import heartbeat
            heartbeat.note(heartbeat.CEILING_UNUSED, sweep.unused())
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


def _loop_spend(a, rc: int, failed: list | None = None, sweep=None) -> int:
    """Fetch, screen, measure and adopt, ONE CANDIDATE AT A TIME.

    Serial by construction, not by accident. An eval sweeping aliases took this
    machine down by loading a 16 GiB model while a 7.8 GiB one was still
    resident (RULE #193). The budget is a ceiling on what this invocation will
    download, and `--top` a ceiling on how many candidates it will carry the
    whole way.
    """
    import argparse as _ap

    from harness import adopt, ceiling, fetching, screen
    from harness import memory_store as ms

    from harness import disk
    failed = failed if failed is not None else []

    print("\n=== retests ===")
    _beat("retests")
    _reopen_retests()
    _reopen_missing_in_snapshot()

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

    # `--top` is an override; unset, the sweep ceiling sizes the fetch, screen and measure. #1084.
    top = int(getattr(a, "top", 0) or 0)
    budget = fetching.budget_gib(getattr(a, "budget_gib", None))
    plan = _sized(top, sweep)

    want = (getattr(a, "lane", "") or "").strip().lower()
    if want:
        print(f"\n(spending only on the {want} lane)")
    print(f"\n=== fetch (up to {plan['screens']}, budget {budget:g} GiB) ===")
    print(f"  {plan['why']}")
    _beat("fetch")
    backlog = len(screen_cmd.screenable_backlog(want))
    held = fetching.held(backlog, plan["screens"])
    if held:
        print(f"  skipped: {held[1]}")
    else:
        from harness.commands import common
        sub = common.parsed("fetch", "--run", limit=plan["screens"] - backlog, lane=getattr(a, "lane", ""),
                            budget_gib=getattr(a, "budget_gib", None),
                            limit_knob="discover_top" if top else "screen_fraction")
        rc = _step("fetch", screen_cmd.cmd_fetch(sub), failed) or rc

    print(f"\n=== screen ===")
    _beat("screen")
    from harness import gguf
    if gguf.pending():
        print("  restarting the router once for the GGUF files day fetches downloaded or the disk sweep removed")
        gguf.relist()
    import time
    until = None if top or sweep is None else time.time() + sweep.remaining() * ceiling.SCREEN_FRACTION
    sub = _ap.Namespace(**{**vars(a), "loop": False, "screen": True, "run": True, "json": False,
                           "limit": top or EVERY, "limit_knob": "discover_top",
                           "screen_until": until, "screen_s": plan["per_s"]})
    rc = _step("screen", discover_cmd.cmd_discover(sub), failed) or rc

    print(f"\n=== measure and adopt ===")
    _beat("measure")
    try:
        measure_cmd.take_incumbents(want)
    except Exception as exc:  # noqa: BLE001 - a lane that cannot take its incumbent keeps the one it has
        print(f"  incumbent from measurement: not checked ({type(exc).__name__}: {exc})", flush=True)
    store = ms.connect()
    try:
        fresh = measure_queue(store, want, top, sweep)
    finally:
        store.close()
    if not fresh:
        print("  nothing survived the screen, so there is nothing to measure. "
              "A screen that rejects everything is the tier doing its job.")
        if sweep is not None:
            sweep.stopped = "nothing survived the screen to measure"
        return rc
    if sweep is not None:
        sweep.stopped = ""
    return _measure_all(a, fresh, sweep, failed, rc)


#: No count cap: the ceiling stops the screen and measure steps. #1084.
EVERY = 1_000_000


def measure_queue(store, want: str, top: int, sweep=None, room=None, slots=None, say=print) -> list[dict]:
    """What the measure step takes, in order: paused runs, repo-lane comparisons, then the families' order. #1100, #1111."""
    queue = _by_family(store, measure_cmd.measurable(store, top or EVERY, want), sweep, room, slots, say)
    return repo_gate.order(measure_cmd.resume_first(store, queue, want), store, want)


def _by_family(store, rows: list[dict], sweep, room=None, slots=None, say=print) -> list[dict]:
    """Demoted families after the rest, then the diversity slots at the head; both said and noted for the morning. #1100, #1111."""
    from harness import family, heartbeat
    st = family.standing(store)
    ordered = family.measure_order(rows, st)
    for r in ordered:
        got, said = st.demotion(r, r.get("lane", ""))
        if said:
            say(f"  family: {r.get('name', '')} {'waits behind the rest' if got else 'keeps its place'}: {said}")
    room = room or measure_cmd.room_for

    def fits(row):
        if sweep is not None and sweep.remaining() <= 0:
            return False, "the sweep ceiling is reached"
        ok, _, why = room(row)
        return ok, why

    queue, picks, lines = family.reserve(ordered, st, fits=fits, slots=slots)
    for line in lines:
        say(f"  {line}")
        if sweep is not None:
            sweep.lines.append(line)
    heartbeat.note(heartbeat.DIVERSITY, {"picks": picks, "lines": lines})
    return queue


def _sized(top: int, sweep) -> dict:
    """How many screens this sweep fetches for, and the seconds one screen is taken to need. #1084."""
    from harness import ceiling, power
    from harness import memory_store as ms
    if top:
        return {"screens": top, "per_s": 0.0, "why": f"--top {top} sets it"}
    store = ms.connect()
    try:
        per = ceiling.screen_s(store)
    finally:
        store.close()
    left = sweep.remaining() if sweep is not None else float(power.SWEEP_CEILING_H) * 3600
    n = ceiling.screens_that_fit(left * ceiling.SCREEN_FRACTION, per)
    return {"screens": n, "per_s": per,
            "why": (f"{n} screen(s) of about {power._hm(per)} fit {ceiling.SCREEN_FRACTION:.0%} "
                    f"of the {power._hm(left)} left of the sweep ceiling")}


def _measure_all(a, fresh: list[dict], sweep, failed: list, rc: int = 0, room=None) -> int:
    """Each measurement in turn; after a memory pause, only those that fit now, smallest first. #813, #1082."""
    room = room or measure_cmd.room_for
    queue, total, i, tight = list(fresh), len(fresh), 0, False
    while queue:
        held = _held_back(sweep, len(queue))
        if held:
            sweep.lines.append(held)
            sweep.stopped, sweep.waiting = held, len(queue)
            if not sweep.halted:
                from harness import cuts
                cuts.cut("sweep_ceiling_h", held, value=sweep.ceiling_s / 3600, kept=total - len(queue), dropped=len(queue))
            break
        if tight:
            row, why = _next_fitting(queue, room)
            if row is None:
                line = f"memory: {len(queue)} measurement(s) do not fit now and wait for the next sweep; {why}"
                print(f"  {line}", flush=True)
                sweep.lines.append(line)
                sweep.stopped, sweep.waiting = line, len(queue)
                break
            queue.remove(row)
        else:
            row = queue.pop(0)
        i += 1
        why = _gated(row, getattr(a, "lane", ""))
        if why:
            print(f"  {why}", flush=True)
            continue
        _beat("measure", candidate=row.get("name", ""), item=i, items=total)
        rc = _step(f"measure {row.get('name', '')}".strip(),
                   measure_cmd._measure_and_adopt(repo_gate.args_for(a, row), row, sweep), failed) or rc
        if sweep is not None and sweep.squeezed:
            # Its model is released by now: re-sample memory before each start from here on.
            print(f"  {row.get('name', '')} was paused for memory; going on with what fits, smallest first",
                  flush=True)
            sweep.squeezed, tight = "", True
    return rc


def _gated(row: dict, want: str) -> str:
    """Why the repo gate holds `row` back this sweep, else "". #889."""
    from harness import memory_store as ms
    store = ms.connect()
    try:
        return repo_gate.blocked(store, row, want)
    finally:
        store.close()


def _next_fitting(queue: list[dict], room) -> tuple[dict | None, str]:
    """The smallest queued measurement that fits now (unknown sizes last), or None and why the smallest does not."""
    sized = []
    for n, row in enumerate(queue):
        ok, need, why = room(row)
        sized.append((need is None, need or 0.0, n, ok, why, row))
    sized.sort(key=lambda t: t[:3])
    for _, _, _, ok, _, row in sized:
        if ok:
            return row, ""
    return None, f"{sized[0][5].get('name', '')}: {sized[0][4]}" if sized else ""


def _held_back(sweep, waiting: int) -> str:
    """Why the measure step starts nothing more this sweep, else "": the ceiling, or a run paused on request. #813."""
    if sweep is None or not (sweep.remaining() <= 0 or sweep.halted):
        return ""
    stop = "a run was paused on request" if sweep.halted else "ceiling reached"
    return f"{stop}: {waiting} measurement(s) wait for the next sweep"


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


def _reopen_missing_in_snapshot() -> list[str]:
    """Requeue for screen the BROKEN screens a loader failed on a file missing from our own snapshot. #911."""
    from harness import memory_store as ms
    store = ms.connect()
    try:
        names = ms.requeue_missing_in_snapshot(store)
        copies = ms.requeue_incomplete_copies(store)
    finally:
        store.close()
    print(f"  requeued {len(names)} screen(s) that failed on our own snapshot")
    for n in names:
        print(f"    {n}")
    print(f"  refetching {len(copies)} snapshot(s) missing files their runner opens (#1040)")
    for n in copies:
        print(f"    {n}")
    return names + copies


def _reopen_unranked() -> list[str]:
    """Requeue for inspect the weights a parent's ranking retired before #954."""
    from harness import heartbeat, memory_store as ms
    began = heartbeat.clock()
    store = ms.connect()
    try:
        names = ms.requeue_unranked(store)
    finally:
        store.close()
    heartbeat.mark(heartbeat.REOPENED_UNRANKED, began)
    print(f"  requeued {len(names)} weight(s) a parent's ranking had retired")
    for n in names:
        print(f"    {n}")
    return names


def _reopen_upstream_committed(fetch=None, client=None) -> dict:
    """Requeue for inspect the commit_after refusals whose upstream has committed since. #961."""
    from harness import inspect as ins, memory_store as ms
    store = ms.connect()
    ins.PACE.start()
    try:
        got = ms.requeue_upstream_committed(
            store, lambda repo, registry: ins.upstream_commit(repo, registry, fetch=fetch, client=client))
    finally:
        ins.PACE.end()
        store.close()
    print(upstream_line(got))
    for r in got["committed"]:
        print(f"    {r['name']}  ({r['until']}, last commit {r['last_commit']})")
    return got


def _move_past_screen() -> list[str]:
    """Move to the measure queue the cases/limit declines past their screen that an older requeue reopened to inspect. #1060."""
    from harness import heartbeat, memory_store as ms
    began = heartbeat.clock()
    store = ms.connect()
    try:
        moved = ms.requeue_reopened_too_far(store)
    finally:
        store.close()
    heartbeat.mark(heartbeat.MOVED_PAST_SCREEN, began)
    print(f"  moved {len(moved)} past-screen reopen(s) from inspect to the measure queue")
    for n in moved:
        print(f"    {n}")
    return moved


def _reopen_revisitable() -> list[dict]:
    """Reopen, to the tier each until gates, the refusals whose until this machine now meets, after the runner-gap rewrite. #1055, #1060."""
    from harness import heartbeat, memory_store as ms
    began = heartbeat.clock()
    store = ms.connect()
    try:
        rows = ms.revisitable(store)
        ms.requeue_revisitable(store, rows=rows)
        spent = ms.revisitable(store, spent=True)
    finally:
        store.close()
    heartbeat.mark(heartbeat.REOPENED_REVISITABLE, began)
    print(f"  requeued {len(rows)} refusal(s) whose until is met here")
    for r in rows:
        outcome, tier = ms.reopens_to(r["until"], r["tier"])
        print(f"    {r['name']}  ({r['until']}) -> {outcome} at {tier}")
    if spent:
        print(f"  left {len(spent)} met until(s) already spent on a reopen that was declined again")
        for r in spent:
            print(f"    {r['name']}  ({r['until']})")
    return rows


def upstream_line(got: dict, requeued: bool = True) -> str:
    """How many commit_after refusals were asked about, answered and reopened. #961."""
    left = got["waiting"] - got["asked"]
    return (f"  asked {got['asked']} of {got['waiting']} commit_after refusal(s) for their upstream's "
            f"last commit: {got['answered']} answered, {len(got['committed'])} committed since"
            + (" and requeued" if requeued else "")
            + (f"; {left} not asked (registry rate-limited)" if left else ""))


def _rederive_attachments() -> dict:
    """Re-read the cards whose attachment an older rule set; every one, the first time. #949."""
    from harness import heartbeat, memory_store as ms
    every = not heartbeat.marked(heartbeat.REDERIVED_ATTACHMENTS)
    began = heartbeat.clock()
    store = ms.connect()
    try:
        got = ms.rederive_attachments(store, every=every)
    finally:
        store.close()
    if every and not got["unread"]:
        heartbeat.mark(heartbeat.REDERIVED_ATTACHMENTS, began)
    print(f"  re-read {got['read']} attachment card(s): {len(got['changed'])} changed, "
          f"{len(got['requeued'])} requeued, {len(got['unread'])} unread, {len(got['gone'])} gone")
    for c in got["changed"]:
        print(f"    {c['name']}: {c['was']} -> {c['now'] or '(a model)'}")
    return got


def _relane_vision() -> list[dict]:
    """Code-lane image-text-to-text rows the text runner cannot load go to the vision lane. #1282."""
    from harness import memory_store as ms
    store = ms.connect()
    try:
        moved = ms.relane_to_vision(store)
        store.commit()
    finally:
        store.close()
    if moved:
        print(f"  moved {len(moved)} image-text-to-text row(s) from code to vision")
    for m in moved:
        print(f"    {m['name']}: by {m['source']}, was {m['state']}")
    return moved


def _reopen_stale_too_big() -> list[str]:
    """Requeue for inspect the too-big refusals judged against a smaller ceiling than this machine's. #880."""
    from harness import heartbeat, memory_store as ms
    began = heartbeat.clock()
    store = ms.connect()
    try:
        names = ms.requeue_stale_too_big(store)
        sized = ms.requeue_old_sizing(store)
    finally:
        store.close()
    heartbeat.mark(heartbeat.REOPENED_TOO_BIG, began)
    heartbeat.mark(heartbeat.REQUEUED_OLD_SIZING, began)
    print(f"  requeued {len(names)} too-big refusal(s) judged against a smaller ceiling")
    for n in names:
        print(f"    {n}")
    print(f"  requeued {len(sized)} refusal(s) sized by the repo total or the library tag (#947)")
    for n in sized:
        print(f"    {n}")
    return names + sized


#: How many runtime declines one loop re-reads the cards of; the rest wait for the next. #950.
REREAD_PER_LOOP = 25


def _reread_runtime_declines(a) -> list[str]:
    """Re-read the cards of screen runtime declines that predate model_type, then rewrite every runtime until by its cause. #950."""
    from harness import heartbeat, memory_store as ms
    from harness.commands import common
    began = heartbeat.clock()
    store = ms.connect()
    try:
        from harness import cuts
        names = cuts.take(ms.cards_to_reread(store), REREAD_PER_LOOP, "screen_reread_per_loop",
                          "runtime decline cards left for the next loop", conn=store)
    finally:
        store.close()
    if names:
        print(f"  re-reading {len(names)} runtime decline card(s) for their model type")
        discover_cmd._report_inspect(common.parsed(
            "discover", "--inspect", repos=names, budget=getattr(a, "budget", 900), top=len(names)))
    store = ms.connect()
    try:
        moved = ms.rewrite_runner_gap_untils(store)
        store.commit()
    finally:
        store.close()
    heartbeat.mark(heartbeat.REWROTE_RUNNER_GAPS, began)
    print(f"  {len(moved)} runtime decline(s) now wait on their cause")
    for n in moved:
        print(f"    {n}")
    return moved


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


def _triage_lines(store, want: str = "", run: bool = False) -> list[str]:
    """Technique proposals into method crossings before the loop crosses its registered methods; drafts only with --run. #993."""
    from harness import technique_triage as tt
    got = tt.triage(store, want=lanes.canonical(want) if want else "") if run else None
    return tt.lines(store, got)


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
    from harness import binding, cuts, runs
    cuts.flush(store)
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
