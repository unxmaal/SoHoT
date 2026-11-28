"""`soh fetch` and the screen tier: what to fetch, what fits, and the screen of what arrived."""
from __future__ import annotations

import contextlib
import re
import time

from harness import cuts, memory, paths, reasons
from harness.commands.common import emit, err, note
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd


def cmd_fetch(a) -> int:
    """What the screen fetches as it starts each candidate, in its order; nothing is downloaded here. #62, #2015."""
    from harness import fetching
    from harness import memory_store as ms

    want = (getattr(a, "lane", "") or "").strip().lower()
    store = ms.connect()
    try:
        rows = fetching.queued(store, lane=want)
    finally:
        store.close()
    testable = [r for r in rows if r.get("lane")]
    orphans = [r for r in rows if not r.get("lane")]
    note(f"{len(testable)} queued, {fetching.free_bytes() / fetching.GIB:.0f} GiB free. Each screen fetches its "
         f"candidate as it starts and removes it when no test is about to run it.")
    for r in testable[:20]:
        size = int(r.get("size_bytes") or 0)
        gib = f"{size / fetching.GIB:5.1f} GiB" if size else "  no size"
        note(f"  {r['score'] or 0:>4.0f}  {gib}  {r['lane']:6s} {r['resolved'] or r['name']}")
    if orphans:
        note(f"\n{len(orphans)} named but NOT queued: nothing here can measure them. Not a verdict on the model -- "
             f"the eval suite has no case, runner or metric for this kind of thing.")
        for r in orphans[:10]:
            note(f"        {r['resolved'] or r['name']}")
    emit(free_bytes=fetching.free_bytes(),
         queued=[{"repo": r["resolved"] or r["name"], "lane": r["lane"], "score": r["score"],
                  "size": int(r.get("size_bytes") or 0)} for r in testable],
         orphans=[r["resolved"] or r["name"] for r in orphans])
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


def _record_prefilter(want: str) -> None:
    """Each queued candidate the prefilter keeps out of the ranked list gets a fetch verdict naming why. #2165."""
    from harness import prefilter
    from harness import memory_store as ms
    store = ms.connect()
    try:
        held = prefilter.split(store, loop_cmd._queueable(store, want)[0])[1]
        if held:
            prefilter.record(store, held)
    finally:
        store.close()


def _screen_plan(want: str) -> list[dict]:
    from harness import prefilter, rank, screen
    from harness import memory_store as ms
    store = ms.connect()
    try:
        # THE SAME DEFECT AS _report_queue, at the tier that actually runs the
        # model. `--top 2` sampled 8 rows of 114 and filtered those, so the
        # loop fetched two image models and then said "nothing queued to
        # screen". Issue #209.
        rows, _ = loop_cmd._queueable(store, want)
        rows = prefilter.split(store, rows)[0]
        # The same store as the fetch's ranking, so both tiers order by one key. #275, #881.
        ranked = rank.rank(rows, serving=rank.serving(),
                           measured_lanes=rank.lanes_with_receipts(store), conn=store)
    finally:
        store.close()
    return screen.plan(ranked)


def _open_lanes(plan: list[dict], record: bool) -> list[dict]:
    """The plan less candidates of a lane the gate closed; a screen run leaves each a queued verdict naming the gate. #2164."""
    from harness import lane_gate
    from harness import memory_store as ms
    if not plan:
        return plan
    store = ms.connect()
    try:
        of = (lambda r: r.get("modality") or r.get("lane") or "")
        kept, gates = lane_gate.keep(store, plan, lane_of=of, say=print)
        if gates and record:
            lane_gate.record(store, [r for r in plan if r not in kept], gates, lane_of=of)
        return kept
    finally:
        store.close()


#: Consecutive same-need memory deferrals after which the screen stops recording another one. #910.
MEMORY_DEFERRALS = 3


def _deferred(store, name: str) -> None:
    cuts.cut("screen_memory_deferrals", f"{name} deferral left unrecorded", conn=store)


def memory_deferrals(conn, name: str) -> tuple[int, str]:
    """How many of a name's newest verdicts in a row are screen memory deferrals of one need, and that need. #910."""
    from harness import memory_store as ms
    streak, need = 0, ""
    for v in conn.execute(
            "SELECT v.tier, v.reason, v.until FROM verdicts v JOIN proposals p "
            "ON p.id = v.proposal_id WHERE p.name = ? ORDER BY v.id DESC", (name,)):
        got = memory.wait_need(v["until"] or "")
        if v["tier"] != ms.SCREEN or v["reason"] != reasons.MEMORY or not got \
                or (need and got != need):
            break
        streak, need = streak + 1, got
    return streak, need


#: Screens of one candidate that ended with the shared server dead, on one runtime version, before it is declined. #1544.
SERVER_KILLS = 2
#: Seconds a screen that ended with the mlx server dead waits for the watchdog to restart it. #1544.
SERVER_BACK_WAIT_S = 600.0
#: Seconds between looks at the restarted server's /health. #1544.
SERVER_BACK_POLL_S = 15.0


def server_kills(conn, name: str, runtime: str, version: str) -> int:
    """How many of a name's screens here ended with the server dead while their runs recorded `runtime` at `version`. #1544."""
    import json
    from harness import memory_store as ms
    got = 0
    for v in conn.execute(
            "SELECT r.environment FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
            "JOIN runs r ON r.id = v.run_id WHERE p.name = ? AND v.tier = ? AND v.machine_id IS ? "
            f"AND v.failure_class IN ({', '.join('?' * len(reasons.SERVER_DIED))})",
            (name, ms.SCREEN, ms.machine_row(conn), *reasons.SERVER_DIED)):
        try:
            versions = json.loads(v["environment"] or "{}").get("versions") or {}
        except (ValueError, AttributeError):
            continue
        got += versions.get(runtime) == version
    return got


def _killer(conn, name: str, runtime: str, version: str, kills: int):
    """kills_server when `kills` reaches screen_server_kills, else None. #1544."""
    from harness import screen
    if not version or kills < SERVER_KILLS:
        return None
    cuts.cut("screen_server_kills", f"{name}: {kills} screens ended with the server dead on {runtime} {version}; declined",
             value=SERVER_KILLS, conn=conn)
    return screen.kills_server(kills, runtime, version)


def repeat_kill(conn, name: str, candidate: str, verdict, environment):
    """A server death's verdict: kills_server once it is the screen_server_kills-th on its run's runtime version, else as given. #1544."""
    from harness import screen
    runtime = screen.engine_runtime(candidate) or screen.LOAD_RUNTIME
    version = ((environment or {}).get("versions") or {}).get(runtime) or ""
    return _killer(conn, name, runtime, version, server_kills(conn, name, runtime, version) + 1) or verdict


def known_killer(conn, name: str, candidate: str):
    """kills_server, unscreened, for one whose screens already killed the server enough on the installed version, else None. #1544."""
    from harness import screen
    runtime = screen.engine_runtime(candidate) or screen.LOAD_RUNTIME
    version = screen._installed(runtime)
    return _killer(conn, name, runtime, version, server_kills(conn, name, runtime, version))


#: Screens of one candidate in a row ending harness_error before it is declined at this limit and the owner paged. #2012.
HARNESS_ERRORS = 3


def harness_errors(conn, name: str) -> int:
    """How many of a name's newest screen verdicts in a row are harness_error. #2012."""
    from harness import memory_store as ms
    streak = 0
    # This machine's screens: another's harness is not the one that failed here.
    for v in conn.execute("SELECT v.failure_class FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                          "WHERE p.name = ? AND v.tier = ? AND v.machine_id IS ? ORDER BY v.id DESC",
                          (name, ms.SCREEN, ms.machine_row(conn))):
        if v["failure_class"] != reasons.HARNESS_ERROR:
            break
        streak += 1
    return streak


def harness_stuck(conn, name: str, verdict):
    """A harness_error that is the screen_harness_errors-th in a row: declined at that limit and paged, else as given. #2012."""
    from harness import knobs, monitor, screen
    if verdict.failure_class != reasons.HARNESS_ERROR or harness_errors(conn, name) + 1 < HARNESS_ERRORS:
        return verdict
    why = (f"{HARNESS_ERRORS} screens in a row could not be delivered (harness_error); the harness needs a fix, "
           f"and a retest or a higher screen_harness_errors reopens it: {verdict.detail}")
    cuts.cut("screen_harness_errors", f"{name}: {why}", conn=conn)
    monitor.alert("service", {"MONIT_SERVICE": "screen", "MONIT_DESCRIPTION": why[:400]})
    return screen.Verdict("declined", why, reasons.LIMIT,
                          f"limit:{knobs.limit('screen_harness_errors', HARNESS_ERRORS, 'screens')}", reasons.HARNESS_ERROR)


def server_back(base: str, conn=None) -> bool:
    """Whether the mlx server at `base` can generate again within SERVER_BACK_WAIT_S, as the watchdog restarts it. #1544."""
    from harness import mlx_server, watchdog
    end = time.monotonic() + SERVER_BACK_WAIT_S
    while True:
        if mlx_server.generating(base, timeout=watchdog.PROBE_TIMEOUT_S):
            return True
        left = end - time.monotonic()
        if left <= 0:
            cuts.cut("screen_server_back_wait", f"{base} did not answer /health within the wait", conn=conn)
            return False
        time.sleep(min(SERVER_BACK_POLL_S, left))


def out_of_time(until: float | None, per_s: float, now: float) -> bool:
    """A screen of `per_s` seconds started now would end past `until`. #1084."""
    return until is not None and now + per_s > until


def snapshot_gap(row: dict, conn) -> str:
    """Why an offline load cannot open a ready row's recorded weights, its rows stood down; "" when it can. #799."""
    from harness import download_state, downloads, fetching, methods
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
            downloads.stand_down(conn, repo, download_state.OFFLINE_GAP)
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


def _todo(full: list[dict], store) -> list[dict]:
    """Ready rows and the ones a screen fetches as it starts them, lanes in turns; `fetch` says how. #1084, #2015."""
    from harness import fetching, methods, screen, wip
    out = []
    for r in full:
        if r["state"] == screen.READY:
            out.append(r)
            continue
        target = methods.weights_of(r["name"]) if methods.is_method(r["name"]) else r["name"]
        if r["state"] != screen.WAITING or not target:
            continue
        got = fetching.row(store, target)
        if got is not None:
            out.append({**r, "fetch": got})
        elif fetching.have(target, store):
            # Its own weights are here and only what it loads beside them is not.
            out.append({**r, "fetch": {}})
    return wip.pull(store, fetching.by_lane_turns(out, store), say=print)


def _fetched(store, r: dict) -> tuple[str, bool]:
    """Fetch what the screen of `r` loads and is not on disk: (why it could not or "", the registry deferred it). #2015."""
    from harness import fetching, methods, screen
    if "fetch" not in r:
        return "", False
    if r["fetch"]:
        got = fetching.for_test(store, r["fetch"])
        if not got["ok"]:
            return got["why"] or "the fetch failed", bool(got.get("deferred"))
    else:
        why = fetching.ensure(store, methods.weights_of(r["name"]) if methods.is_method(r["name"]) else r["name"],
                              via="the screen", tier="fetch")
        if why:
            return why, False
    again = screen.plan([r])[0]
    return ("" if again["state"] == screen.READY else again["why_not"]), False


def _release(store, r: dict) -> None:
    """The weights a screen fetched or found go when its verdict keeps nothing for the measure step. #2015."""
    from harness import disk, downloads, methods
    names = [n for n in (r["name"], r.get("resolved"), methods.weights_of(r["name"]) if methods.is_method(r["name"])
                         else "") if n]
    if not any(downloads.path_of(n, store) for n in names):
        return
    store.commit()
    disk.sweep(conn=store, names=names, say=lambda line: print(f"   {line.strip()}"))


def passed_over(store, left: list[dict], why: str) -> None:
    """Each fetchable row a screen's bound left gets a pass-over verdict, the days rank ages it by. #1288, #2020."""
    from harness import fetching
    from harness import memory_store as ms
    # The day in the detail: a verdict restating its state is not written again (#184), and rank counts days.
    day = time.strftime("%Y-%m-%d", time.gmtime())
    for r in left:
        row = r.get("fetch")
        if row and (fetching.why_not(row) or ("",))[0] not in fetching.SILENT:
            ms.decide_or_skip(store, row["name"], "queued", tier=ms.FETCH, detail=f"not fetched {day}: {why}"[:600],
                              reason=reasons.LIMIT, failure_class=reasons.PASSED_OVER, commit=False)
    store.commit()


def _report_screen(a) -> int:
    """Run the cheapest real thing, and record whether it ran at all. #53.

    SAYS WHAT IT WOULD DO AND STOPS, unless told otherwise. `--run` is the same
    convention `lh fetch` uses, and for the same reason: this is the first tier
    that spends real time and real memory, and one that starts doing so because
    something ranked well is how a laptop ends up unusable overnight.
    """
    from harness import screen, wip
    from harness import memory_store as ms

    want = (getattr(a, "lane", "") or "").strip().lower()
    if getattr(a, "run", False):
        _record_prefilter(want)
    full = _open_lanes(_screen_plan(want), record=bool(getattr(a, "run", False)))
    if not full:
        print("nothing queued to screen")
        return 0
    # Ready rows come from the whole plan: the rank head is often rows the
    # fetch skipped for budget, which crowded out what it fetched. #376.
    ready = [r for r in full if r["state"] == screen.READY]
    planned = full[:getattr(a, "top", None) or 25]
    planned += [r for r in ready if r not in planned]
    if not getattr(a, "run", False):
        print(f"\n{len(planned)} candidate(s), {len(ready)} ready to screen:")
        for r in planned:
            print(f"\n  {r['state']:16} {r['name']}")
            print(f"    {r['why_not']}")
            if r["state"] == screen.READY:
                print(f"    {' '.join(screen.argv(r))}")
        print("\n  --run to screen them; each screen fetches its candidate as it starts and removes it "
              "when no test is about to run it")
        return 0
    store = ms.connect()
    try:
        todo = _todo(full, store)
        if not todo:
            # An empty screen is a result, not a failure (#328).
            print("nothing is ready to screen, and no queued candidate can be fetched for one")
            return 0
        limit, taken = getattr(a, "limit", 1), 0
        until, per = getattr(a, "screen_until", None), float(getattr(a, "screen_s", 0) or 0)
        # The screens the lanes pull are the share this step needs; the rest of the ceiling is the measure step's. #2165.
        until = wip.share_until(until, time.time(), len(todo), per)
        for r in todo:
            if taken >= limit:
                cuts.cut(getattr(a, "limit_knob", None) or "discover_top",
                         f"the screen count is reached; {r['name']} and the rest of the ready rows wait",
                         value=limit, kept=taken, dropped=len(todo) - todo.index(r), conn=store)
                passed_over(store, todo[todo.index(r):], "the screen count is reached")
                break
            # The sweep ceiling's screen share, not a count, ends the step. #1084.
            if out_of_time(until, per, time.time()):
                left = len(todo) - todo.index(r)
                print(f"\n   the screen share of the sweep ceiling is spent: {left} candidate(s) "
                      f"wait for the next sweep", flush=True)
                cuts.cut("screen_fraction",
                         f"the screen share of the sweep ceiling is spent; {r['name']} and the rest wait",
                         kept=taken, dropped=left, conn=store)
                passed_over(store, todo[todo.index(r):], "the screen share of the sweep ceiling is spent")
                break
            print(f"\n── {r['name']}", flush=True)
            got = None
            try:
                started, got, stop = _screen_one(a, store, r)
            finally:
                if got != "screened":
                    _release(store, r)
            taken += started
            if stop is not None:
                return stop
            # A screen that did not stay in hand leaves its lane room for the next candidate it would pull. #2165.
            more = todo.backfill(r) if got != "screened" and hasattr(todo, "backfill") else None
            if more is not None:
                todo.append(more)
    finally:
        store.close()
    return 0


def _no_window(store, r: dict, why_not: str, why: str) -> tuple[bool, str | None, int | None]:
    """The queued verdict of a candidate whose screen window was refused; its weights stay unfetched until room is free. #2127."""
    from harness import memory_store as ms
    print(f"   QUEUED: no screen window: {why}")
    ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN, reason=reasons.MEMORY,
                      detail=f"not screened: {why_not}; no screen window: {why}"[:600],
                      until=memory.wait_for(r["name"], spec=r["candidate"], parallel=1, remote=True))
    return False, "queued", None


def _screen_one(a, store, r: dict) -> tuple[bool, str | None, int | None]:
    """Fetch, check and screen one candidate: (a screen started, its outcome or None, the step's exit when it stops). #2015."""
    import subprocess

    from harness import audio_models, candidates, heartbeat, mlx_server, router, screen, screen_window
    from harness import memory_store as ms

    # Headroom, including what is already resident, sized from the listing before anything is fetched. #284, #2015.
    room, why_not = memory.check_model(r["name"], spec=r["candidate"], parallel=1, remote=True)
    need = None if room else memory.need_gb(r["name"], None, r["candidate"], 1, True)
    windowed = not room and screen_window.wanted(need, landing=memory.landing_gb(r["name"], need))
    if windowed:
        print(f"   WINDOW: {why_not}; the pinned set is released for this screen")
    if not room and not windowed:
        # A memory deferral screens nothing, so it does not spend a slot. #910.
        print(f"   QUEUED: {why_not}")
        streak, need = memory_deferrals(store, r["name"])
        until = memory.wait_for(r["name"], spec=r["candidate"], parallel=1, remote=True)
        got = memory.wait_need(until)
        if streak >= MEMORY_DEFERRALS and got and got == need:
            _deferred(store, r["name"])
            print(f"   deferred {streak} times for {need} GB; left queued")
            return False, None, None
        ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN, detail=f"not screened: {why_not}"[:600],
                          reason=reasons.MEMORY, until=until)
        return False, "queued", None
    # Screening it again would only kill the shared server again. #1544.
    known = known_killer(store, r["name"], r["candidate"])
    if known:
        print(f"   {known.outcome.upper()}: {known.detail}")
        ms.decide_or_skip(store, r["name"], known.outcome, tier=ms.SCREEN, detail=known.detail[:600],
                          reason=known.reason, until=known.until, failure_class=known.failure_class)
        return False, known.outcome, None
    # A window the screen could not be granted is found out before the weights are fetched for it. #2127.
    no_window = screen_window.refusal(screen.deadline_s(r["candidate"], r["modality"])) if windowed else ""
    if no_window:
        return _no_window(store, r, why_not, no_window)
    # The test fetches what it runs, right before it runs it. #2015.
    missing, deferred = _fetched(store, r)
    if missing:
        print(f"   NOT FETCHED: {missing}")
        return False, None, 0 if deferred else None
    # Weights an offline load cannot open go back to fetch, never to a verdict. #799.
    gap = snapshot_gap(r, store)
    if gap:
        print(f"   QUEUED: {gap}; the next screen fetches it again")
        ms.decide_or_skip(store, r["name"], "queued", tier=ms.FETCH,
                          detail=f"not screened: {gap}; the next screen fetches it again"[:600], reason=reasons.HARNESS)
        return False, "queued", None
    # Its own receipt directory, not the newest for the modality. #282.
    outdir = paths.unused_run(f"screen-{int(time.time())}", f"-{r['modality']}")
    proc, unrestored = None, ""
    try:
        # The lock is taken here so its wait reaches the heartbeat; the child inherits it. #705.
        with heartbeat.held("eval", screen.deadline_s(r["candidate"], r["modality"]), say=lambda m: print(f"   {m}", flush=True)):
            with (screen_window.opened(screen.deadline_s(r["candidate"], r["modality"]), f"a screen window for {r['name']}")
                  if windowed else contextlib.nullcontext()):
                if windowed:
                    short = screen_window.still_short(memory.need_gb(r["name"], None, r["candidate"], 1, True))
                    if short:
                        raise screen_window.Refused(short)
                proc = subprocess.run(screen.argv(r, outdir=outdir), capture_output=True, text=True)
    except screen_window.Refused as exc:
        if proc is None:
            return _no_window(store, r, why_not, str(exc))
        unrestored = str(exc)
    except OSError as exc:
        print(f"   QUEUED: the screen could not start: {exc}")
        ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN,
                          detail=f"not screened: the screen could not start: {exc}"[:600], reason=reasons.HARNESS,
                          failure_class=reasons.HARNESS_ERROR)
        return True, "queued", None
    # The RUN's own summary, read from what it wrote rather than parsed out of its chatter. #53.
    stored = measure_cmd._receipt_at(outdir)
    summary = stored.get("summary") if stored else None
    ran = (stored or {}).get("specs") or {}
    candidates.from_receipt(store, ran, lane=r["modality"], proposals={s: r["name"] for s in ran.values()})
    cid = candidates.ensure(store, r["candidate"], proposal=r["name"], lane=r["modality"])
    key = candidates.key_for(store, r["candidate"])
    # Read once, here, and only when the run wrote no receipt. #408.
    verdict = verdict_of_run(proc.returncode, proc.stderr, summary, r["candidate"], key=key,
                             facts=ms.this_machine(), card=r, lane=r["modality"])
    if verdict.failure_class == reasons.LOAD_LOG_UNREAD:
        # The router's log says why; its child's lines are kept with the run. #953.
        from harness import load_log
        verdict = load_log.redecide(verdict, r["candidate"], r["name"], outdir, store)
    if verdict.failure_class in reasons.SERVER_DIED:
        # One that kills the server on every screen is no harness fault to requeue nightly. #1544.
        verdict = repeat_kill(store, r["name"], r["candidate"], verdict, (stored or {}).get("environment"))
    # A harness fault that never clears is paged once, not requeued every night. #2012.
    verdict = harness_stuck(store, r["name"], verdict)
    tier = ms.SCREEN
    if verdict.failure_class in reasons.REFETCH:
        from harness import download_state, downloads
        downloads.stand_down(store, r["name"], download_state.REFETCH_CLASS)
        tier = ms.FETCH
    if verdict.failure_class == reasons.ATTACHMENT:
        # A drafter is the fetch tier's attachment decline, so no retest refetches it. #1039.
        ms.set_attachment(store, r["name"], screen.DRAFTER)
        tier = ms.FETCH
    got, why = verdict.outcome, verdict.detail
    print(f"   {got.upper()}: {why}")
    if proc.returncode != 0:
        err(proc.stderr.strip()[-400:] or "no stderr")
    ms.decide_or_skip(store, r["name"], got, tier=tier, detail=screen_detail(why, proc.stderr, summary)[:600],
                      run_id=(stored or {}).get("run_id"), reason=verdict.reason, until=verdict.until,
                      candidate_id=cid, failure_class=verdict.failure_class)
    router.release_spec(r["candidate"], f"screened {r['name']}")
    mlx_server.release_spec(r["candidate"], f"screened {r['name']}")
    audio_models.release_spec(r["candidate"], f"screened {r['name']}")
    if unrestored:
        print(f"   the pinned set is not back after the window: {unrestored}; stopping the screen (#2045)")
        return True, got, 1
    if verdict.failure_class not in reasons.STOPS:
        return True, got, None
    print(f"   {verdict.failure_class}: the model server or GPU is suspect; stopping the screen so the rest "
          f"are not spent on it (#404)")
    if verdict.failure_class in reasons.SERVER_DIED and not screen.engine_runtime(r["candidate"]):
        from harness import serving
        print(f"   waiting up to {SERVER_BACK_WAIT_S:g} s for the watchdog to restart it", flush=True)
        if server_back(serving.MLX_URL, store):
            # The candidate is recorded and the server is back: not a failed sweep. #1544.
            print("   the model server generates again; the sweep goes on")
            return True, got, 0
    return True, got, 1
