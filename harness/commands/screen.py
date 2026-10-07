"""`soh fetch` and the screen tier: what to fetch, what fits, and the screen of what arrived."""
from __future__ import annotations

import time

from harness import memory, paths, reasons
from harness.commands.common import emit, err, note
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd


def cmd_fetch(a) -> int:
    """Download what the inspect tier queued. Issue #62."""
    from harness import fetching, inspect as ins
    from harness import memory_store as ms

    want = (getattr(a, "lane", "") or "").strip().lower()
    store = ms.connect()
    try:
        rows = fetching.queued(store, lane=want)
        if not rows:
            note(f"nothing queued in the {want} lane. "
                 f"`soh discover --inspect` fills the queue." if want else
                 "nothing queued. `soh discover --inspect` fills the queue.")
            emit(queued=[], orphans=[])
            return 0
        if not a.run:
            testable = [r for r in rows if r.get("lane")]
            orphans = [r for r in rows if not r.get("lane")]
            note(f"\n{len(testable)} queued, "
                 f"{fetching.free_bytes() / fetching.GIB:.0f} GiB free. "
                 f"--run to start, one at a time. The score is the judged "
                 f"score of the repo that named the weight.")
            for r in testable[:20]:
                size = int(r.get("size_bytes") or 0)
                gib = f"{size / fetching.GIB:5.1f} GiB" if size else "  no size"
                note(f"  {r['score'] or 0:>4.0f}  {gib}  {r['lane']:6s} "
                     f"{r['resolved'] or r['name']}")
            if orphans:
                note(f"\n{len(orphans)} named but NOT queued: nothing here can "
                     f"measure them. Not a verdict on the model -- the eval "
                     f"suite has no case, runner or metric for this kind of "
                     f"thing, and building one is sometimes the work.")
                for r in orphans[:10]:
                    note(f"        {r['resolved'] or r['name']}")
            emit(free_bytes=fetching.free_bytes(),
                 queued=[{"repo": r["resolved"] or r["name"], "lane": r["lane"],
                          "score": r["score"], "size": int(r.get("size_bytes") or 0)}
                         for r in testable],
                 orphans=[r["resolved"] or r["name"] for r in orphans])
            return 0
        gib = getattr(a, "budget_gib", None)
        budget = int(float(gib) * fetching.GIB) if gib else None
        fetched = []
        for got in fetching.run(store, limit=a.limit, lane=want,
                                budget=budget):
            fetched.append(got)
            note(f"  {'OK  ' if got['ok'] else 'skip'} {got['repo']}: {got['why']}")
    finally:
        store.close()
    emit(fetched=fetched)
    return 0


def _judge_fits(fits, store_path=None) -> int:
    """Score inspected candidates with the facts the clone produced. #69.

    Ordering matters: INSPECT runs before JUDGE now. Cheapest-first was never
    the real justification for the old order -- inspect costs seconds and the
    judge costs about a second -- and the judge scoring a generic description
    3/10 while the inspect tier had already proved the thing MLX-native was the
    tier with more evidence losing to the tier with less.
    """
    from harness import judge
    from harness import memory_store as ms
    try:
        rubric = judge.load()
    except judge.JudgeError as exc:
        return err(str(exc))
    store = ms.connect(store_path)
    try:
        print("\n  judged, with the source read first:")
        for f in fits:
            weights = (f"{f.smallest / (1024**3):.1f} to "
                       f"{f.largest / (1024**3):.1f} GiB" if f.largest else "")
            item = judge.describe(
                f.repo, why=f.description, source="github-crowd",
                inspected=f"{f.verdict}: {f.why}",
                platform=("MLX-native" if f.mlx else
                          "torch/MPS" if f.mps else ""),
                weights=weights)
            try:
                score, why = judge.score(item, rubric)
            except Exception as exc:  # noqa: BLE001
                err(f"{f.repo}: {exc}")
                continue
            print(f"    {score:2d}/10  {f.repo:36.36s} {why[:56]}")
            try:
                ms.decide(store, f.repo, "queued", tier=ms.JUDGE, score=score,
                          reason=reasons.CANDIDATE,
                          rubric=rubric.stamp, judge=rubric.model,
                          detail=why[:200])
            except (KeyError, ms.IllegalTransition):
                pass
    finally:
        store.close()
    return 0


def _screen_plan(want: str) -> list[dict]:
    from harness import rank, screen
    from harness import memory_store as ms
    store = ms.connect()
    try:
        # THE SAME DEFECT AS _report_queue, at the tier that actually runs the
        # model. `--top 2` sampled 8 rows of 114 and filtered those, so the
        # loop fetched two image models and then said "nothing queued to
        # screen". Issue #209.
        rows, _ = loop_cmd._queueable(store, want)
    finally:
        store.close()
    ranked = rank.rank(rows, serving=rank.serving(),
                       measured_lanes=rank.lanes_with_receipts())
    return screen.plan(ranked)


def screenable_backlog(want: str = "", plan=None, room=None) -> list[str]:
    """On disk, runnable, and fitting in memory now: what a fetch would queue behind. #396."""
    from harness import screen
    plan = _screen_plan(want) if plan is None else plan
    room = room or (lambda r: memory.check_model(r["name"], spec=r["candidate"])[0])
    return [r["name"] for r in plan if r["state"] == screen.READY and room(r)]


def _report_screen(a) -> int:
    """Run the cheapest real thing, and record whether it ran at all. #53.

    SAYS WHAT IT WOULD DO AND STOPS, unless told otherwise. `--run` is the same
    convention `lh fetch` uses, and for the same reason: this is the first tier
    that spends real time and real memory, and one that starts doing so because
    something ranked well is how a laptop ends up unusable overnight.
    """
    import subprocess

    from harness import candidates, rank, router, screen
    from harness import memory_store as ms

    want = (getattr(a, "lane", "") or "").strip().lower()
    full = _screen_plan(want)
    if not full:
        print("nothing queued to screen")
        return 0
    # Ready rows come from the whole plan: the rank head is often rows the
    # fetch skipped for budget, which crowded out what it fetched. #376.
    ready = [r for r in full if r["state"] == screen.READY]
    planned = full[:getattr(a, "top", 5)]
    planned += [r for r in ready if r not in planned]
    if not getattr(a, "run", False):
        print(f"\n{len(planned)} candidate(s), {len(ready)} ready to screen:")
        for r in planned:
            print(f"\n  {r['state']:16} {r['name']}")
            print(f"    {r['why_not']}")
            if r["state"] == screen.READY:
                print(f"    {' '.join(screen.argv(r))}")
        print("\n  --run to screen the ready ones; nothing is downloaded either "
              "way")
        return 0
    if not ready:
        # An empty screen is a result, not a failure (#328).
        print("nothing is ready to screen: fetch weights first, and note "
              "that a screen never downloads")
        return 0

    store = ms.connect()
    try:
        for r in ready[:getattr(a, "limit", 1)]:
            print(f"\n── {r['name']}", flush=True)
            # Headroom, including what is already resident. #284.
            room, why_not = memory.check_model(r["name"], spec=r["candidate"])
            if not room:
                print(f"   QUEUED: {why_not}")
                ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN,
                                  detail=f"not screened: {why_not}"[:600],
                                  reason=reasons.MEMORY,
                                  until=f"memory_gb:>{memory.available_gb():.1f}")
                continue
            # Its own receipt directory, not the newest for the modality. #282.
            outdir = paths.runs() / f"screen-{int(time.time())}-{r['modality']}"
            try:
                proc = subprocess.run(screen.argv(r, outdir=outdir),
                                      capture_output=True, text=True)
            except OSError as exc:
                print(f"   QUEUED: the screen could not start: {exc}")
                ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN,
                                  detail=f"not screened: the screen could not start: "
                                         f"{exc}"[:600], reason=reasons.HARNESS)
                continue
            # The RUN's own summary, read from what it wrote rather than parsed
            # out of its chatter: a tier that infers an outcome from stdout is
            # a tier that reports success when the format changes.
            stored = measure_cmd._receipt_at(outdir)
            summary = stored.get("summary") if stored else None
            ran = (stored or {}).get("specs") or {}
            candidates.from_receipt(store, ran, lane=r["modality"],
                                    proposals={s: r["name"] for s in ran.values()})
            cid = candidates.ensure(store, r["candidate"], proposal=r["name"],
                                    lane=r["modality"])
            key = candidates.key_for(store, r["candidate"])
            # Read once, here, and only when the run wrote no receipt. #408.
            stderr_class = "" if summary is not None else reasons.classify(
                (proc.stderr or "")[-2000:], reasons.STDERR, r["candidate"])
            verdict = screen.outcome(proc.returncode, summary,
                                     candidate=r["candidate"], key=key,
                                     stderr_class=stderr_class,
                                     facts=ms.this_machine())
            got, why = verdict.outcome, verdict.detail
            print(f"   {got.upper()}: {why}")
            if proc.returncode != 0:
                err(proc.stderr.strip()[-400:] or "no stderr")
            # The stderr tail stays as evidence for a person; the reason and
            # the class are the columns code reads. #281, #408.
            evidence = " ".join((proc.stderr or "").split())[-300:]
            detail = f"{why} || {evidence}" if evidence else why
            ms.decide_or_skip(store, r["name"], got, tier=ms.SCREEN,
                              detail=detail[:600],
                              run_id=(stored or {}).get("run_id"),
                              reason=verdict.reason, until=verdict.until,
                              candidate_id=cid)
            router.release_spec(r["candidate"], f"screened {r['name']}")
            if verdict.failure_class in reasons.STOPS:
                print(f"   {verdict.failure_class}: the model server or GPU is "
                      f"suspect; stopping the screen so the rest are not "
                      f"spent on it (#404)")
                return 1
    finally:
        store.close()
    return 0
