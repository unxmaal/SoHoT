"""`soh fetch` and the screen tier: what to fetch, what fits, and the screen of what arrived."""
from __future__ import annotations

import re
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
        budget = int(fetching.budget_gib(getattr(a, "budget_gib", None)) * fetching.GIB)
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
        # The same store as the fetch's ranking, so both tiers order by one key. #275, #881.
        ranked = rank.rank(rows, serving=rank.serving(),
                           measured_lanes=rank.lanes_with_receipts(store), conn=store)
    finally:
        store.close()
    return screen.plan(ranked)


#: Consecutive same-need memory deferrals after which the screen stops recording another one. #910.
MEMORY_DEFERRALS = 3

_NEEDS = re.compile(r"needs (\d+(?:\.\d+)?) GB")


def memory_deferrals(conn, name: str) -> tuple[int, str]:
    """How many of a name's newest verdicts in a row are screen memory deferrals of one need, and that need. #910."""
    from harness import memory_store as ms
    streak, need = 0, ""
    for v in conn.execute(
            "SELECT v.tier, v.reason, v.detail FROM verdicts v JOIN proposals p "
            "ON p.id = v.proposal_id WHERE p.name = ? ORDER BY v.id DESC", (name,)):
        got = _NEEDS.search(v["detail"] or "")
        if v["tier"] != ms.SCREEN or v["reason"] != reasons.MEMORY or not got \
                or (need and got.group(1) != need):
            break
        streak, need = streak + 1, got.group(1)
    return streak, need


def screenable_backlog(want: str = "", plan=None, room=None, deferred=None) -> list[str]:
    """On disk, runnable, fitting in memory now, and not deferred for memory last screen: what a fetch would queue behind. #396, #910."""
    from harness import screen
    plan = _screen_plan(want) if plan is None else plan
    from harness import methods
    # One screen request's KV beside the weights, where config.json gives a shape. #699.
    room = room or (lambda r: memory.check_model(r["name"], spec=r["candidate"], parallel=1)[0])
    if deferred is None:
        from harness import memory_store as ms
        store = ms.connect()
        try:
            held = {r["name"] for r in plan if r["state"] == screen.READY
                    and memory_deferrals(store, r["name"])[0]}
        finally:
            store.close()
        deferred = held.__contains__
    # A method crossing downloads nothing, so no download waits behind it. #576.
    return [r["name"] for r in plan if r["state"] == screen.READY
            and not methods.is_method(r["name"]) and not deferred(r["name"]) and room(r)]


def snapshot_gap(row: dict, conn) -> str:
    """Why an offline load cannot open a ready row's recorded weights, its rows stood down; "" when it can. #799."""
    from harness import downloads, fetching, methods
    name = row["name"]
    target = methods.weights_of(name) if methods.is_method(name) else name
    if not target:
        return ""
    for repo in [target] + fetching.requires(target, conn):
        path = downloads.path_of(repo, conn)
        if path is None:
            continue
        kind = downloads.GGUF if path.name.lower().endswith(".gguf") else downloads.HUB
        gap = downloads.offline_gap(kind, path)
        if gap:
            downloads.stand_down(conn, repo)
            return gap
    return ""


def verdict_of_run(returncode: int, stderr: str, summary, candidate: str,
                   key: str = "", facts: dict | None = None, card=None, lane: str = ""):
    """One finished screen process's verdict; stderr is classed only without a receipt, and the card picks a runtime gap's until."""
    from harness import screen
    tail = "" if summary is not None else (stderr or "")[-2000:]
    stderr_class = reasons.classify(tail, reasons.STDERR, candidate) if tail else ""
    return screen.outcome(returncode, summary, candidate=candidate, key=key,
                          stderr_class=stderr_class, facts=facts, evidence=tail, card=card, lane=lane)


_PY_WARNING = re.compile(r"^\S.*:\d+: \w*Warning: ")


def _without_warnings(stderr: str) -> str:
    """stderr less Python warnings and the source line each one quotes. #879."""
    kept, skip = [], False
    for line in (stderr or "").splitlines():
        if _PY_WARNING.match(line):
            skip = True
            continue
        if skip and line[:1].isspace():
            skip = False
            continue
        skip = False
        kept.append(line)
    return "\n".join(kept)


def screen_detail(why: str, stderr: str, summary) -> str:
    """A screen verdict's detail: the receipt is the evidence when there is one, else the stderr tail less warnings. #281, #879."""
    if summary is not None:
        return why[:600]
    evidence = " ".join(_without_warnings(stderr).split())[-300:]
    return (f"{why} || {evidence}" if evidence else why)[:600]


def _report_screen(a) -> int:
    """Run the cheapest real thing, and record whether it ran at all. #53.

    SAYS WHAT IT WOULD DO AND STOPS, unless told otherwise. `--run` is the same
    convention `lh fetch` uses, and for the same reason: this is the first tier
    that spends real time and real memory, and one that starts doing so because
    something ranked well is how a laptop ends up unusable overnight.
    """
    import subprocess

    from harness import candidates, heartbeat, rank, router, screen
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
        limit, taken = getattr(a, "limit", 1), 0
        for r in ready:
            if taken >= limit:
                break
            print(f"\n── {r['name']}", flush=True)
            # Weights an offline load cannot open go back to fetch, never to a verdict. #799.
            gap = snapshot_gap(r, store)
            if gap:
                print(f"   QUEUED: {gap}; back to fetch")
                ms.decide_or_skip(store, r["name"], "queued", tier=ms.FETCH,
                                  detail=f"not screened: {gap}; soh fetch --run"[:600],
                                  reason=reasons.HARNESS)
                continue
            # Headroom, including what is already resident. #284.
            room, why_not = memory.check_model(r["name"], spec=r["candidate"], parallel=1)
            if not room:
                # A memory deferral screens nothing, so it does not spend a slot. #910.
                print(f"   QUEUED: {why_not}")
                streak, need = memory_deferrals(store, r["name"])
                got = _NEEDS.search(why_not)
                if streak >= MEMORY_DEFERRALS and got and got.group(1) == need:
                    print(f"   deferred {streak} times for {need} GB; left queued "
                          f"and out of the fetch's wait")
                    continue
                ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN,
                                  detail=f"not screened: {why_not}"[:600],
                                  reason=reasons.MEMORY,
                                  until=memory.wait_for(r["name"], spec=r["candidate"], parallel=1))
                continue
            taken += 1
            # Its own receipt directory, not the newest for the modality. #282.
            outdir = paths.runs() / f"screen-{int(time.time())}-{r['modality']}"
            try:
                # The lock is taken here so its wait reaches the heartbeat; the child inherits it. #705.
                with heartbeat.held("eval", screen.deadline_s(r["candidate"]),
                                    say=lambda m: print(f"   {m}", flush=True)):
                    proc = subprocess.run(screen.argv(r, outdir=outdir),
                                          capture_output=True, text=True)
            except OSError as exc:
                print(f"   QUEUED: the screen could not start: {exc}")
                ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN,
                                  detail=f"not screened: the screen could not start: "
                                         f"{exc}"[:600], reason=reasons.HARNESS,
                                  failure_class=reasons.HARNESS_ERROR)
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
            verdict = verdict_of_run(proc.returncode, proc.stderr, summary,
                                     r["candidate"], key=key, facts=ms.this_machine(), card=r,
                                     lane=r["modality"])
            if verdict.failure_class == reasons.LOAD_LOG_UNREAD:
                # The router's log says why; its child's lines are kept with the run. #953.
                from harness import load_log
                verdict = load_log.redecide(verdict, r["candidate"], r["name"], outdir, store)
            tier = ms.SCREEN
            if verdict.failure_class in reasons.REFETCH:
                from harness import downloads
                downloads.stand_down(store, r["name"])
                tier = ms.FETCH
            if verdict.failure_class == reasons.ATTACHMENT:
                # A drafter is the fetch tier's attachment decline, so no retest refetches it. #1039.
                ms.set_attachment(store, r["name"], screen.DRAFTER)
                tier = ms.FETCH
            got, why = verdict.outcome, verdict.detail
            print(f"   {got.upper()}: {why}")
            if proc.returncode != 0:
                err(proc.stderr.strip()[-400:] or "no stderr")
            detail = screen_detail(why, proc.stderr, summary)
            ms.decide_or_skip(store, r["name"], got, tier=tier,
                              detail=detail[:600],
                              run_id=(stored or {}).get("run_id"),
                              reason=verdict.reason, until=verdict.until,
                              candidate_id=cid, failure_class=verdict.failure_class)
            router.release_spec(r["candidate"], f"screened {r['name']}")
            if verdict.failure_class in reasons.STOPS:
                print(f"   {verdict.failure_class}: the model server or GPU is "
                      f"suspect; stopping the screen so the rest are not "
                      f"spent on it (#404)")
                return 1
    finally:
        store.close()
    return 0
