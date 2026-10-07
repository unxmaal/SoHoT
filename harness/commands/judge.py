"""`soh judge` and `soh rubric`: human and model judgement of runs and of the store."""
from __future__ import annotations

from pathlib import Path
import dataclasses
import json
import time

from harness import paths, reasons
from harness.commands.common import emit, err, note
from harness.commands import adopt as adopt_cmd
from harness.commands import discover as discover_cmd
from harness.commands import measure as measure_cmd


def _evalset(name: str) -> Path:
    p = Path(name).expanduser()
    return p if p.is_dir() else paths.home() / "evalsets" / name


def cmd_rubric(a) -> int:
    """Label an eval set by hand, then score local models against it. #286."""
    from harness import label_server, rubric_eval as rv

    root = _evalset(a.set)
    try:
        s = rv.load_set(root)
    except (OSError, ValueError, KeyError) as exc:
        return err(f"no usable eval set at {root}: {exc}")
    if a.action == "label":
        label_server.serve(root, port=a.port, repeat_rate=a.repeat_rate,
                           open_browser=not a.no_browser)
        return 0
    if a.action == "status":
        agree, total = rv.self_agreement(root)
        note(f"{s.rubric.stamp}: {len(rv.labels(root))} of {len(s.items)} "
             f"labelled, {len(rv.gold(root))} decided, "
             f"self-agreement {agree}/{total} on repeats")
        emit(rubric=s.rubric.stamp, items=len(s.items),
             labelled=len(rv.labels(root)), decided=len(rv.gold(root)),
             self_agreement=[agree, total])
        return 0
    candidates = [c.strip() for c in (a.candidates or "").split(",") if c.strip()]
    if not candidates:
        return err("--candidates is required for run")
    try:
        from harness import exclusive
        with exclusive.held("eval", announce=lambda m: note(m, flush=True)):
            report = rv.run(s, candidates, a.gateway)
    except ValueError as exc:
        return err(str(exc))
    out = paths.runs() / f"rubric-{time.strftime('%Y%m%d-%H%M%S')}-{s.rubric.name}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(report, indent=2),
                                      encoding="utf-8")
    agree, total = report["ceiling"]
    note(f"{report['rubric']}  floor {report['floor']:.2f} (always the most "
         f"common label)  ceiling {agree}/{total} (your repeats)")
    for model, row in report["candidates"].items():
        note(f"  {model:24} agree {row['agree']}/{row['n']} "
             f"({row['agreement']:.2f})  valid {row['valid']}/{row['n']}  "
             f"median {row['median_s']}s"
             f"{'' if row['beats_floor'] else '  NOT above the floor'}")
    note(f"receipt: {out / 'results.json'}")
    emit(path=out / "results.json", report=report)
    return 0


def _say_adopted(store, lane: str, verdict) -> None:
    """Print what a by-hand adoption rests on, what it costs, and where it serves. #485."""
    import json
    from harness import adopt
    if not verdict.adopt:
        return
    row = store.execute(
        "SELECT a.*, c.spec FROM adoptions a JOIN candidates c "
        "ON c.id = a.candidate_id WHERE a.lane = ? ORDER BY a.id DESC LIMIT 1",
        (lane,)).fetchone()
    if not row:
        return
    note(f"  adopted {row['spec']} for {lane}: "
         f"{adopt.describe(dict(row), row['machine_id'])}")
    note(f"  {adopt.cost_text(json.loads(row['cost'] or '{}'))}")
    if row["all_machines"]:
        for m in store.execute("SELECT id, hw_model FROM machines ORDER BY id"):
            ok, why = adopt.fit(store, row["candidate_id"], m["id"])
            note(f"  machine {m['id']} ({m['hw_model']}): "
                 f"{'serves' if ok else 'REFUSED'}, {why}")


def cmd_judge(a) -> int:
    """Serve the page a person votes on, for a lane no program can score.

    Some capabilities have no metric -- not because the right one has not been
    found, but because the field has none. There is no per-clip
    style-similarity measure; Frechet Audio Distance is distributional and
    cannot score one clip; human preference studies are the ground truth for
    music generation. This project hit that wall three times and answered by
    not building the capability. Issue #273.
    """
    from harness import adopt, candidates, human, judge_server, lanes, winners
    from harness import memory_store as ms

    run = Path(a.run).expanduser()
    if not run.is_absolute():
        run = paths.home() / "runs" / run
    receipt = measure_cmd._receipt_at(run)
    if not receipt:
        return err(f"no stored run for {run}")
    lane = (a.lane or receipt.get("receipt", {}).get("modality") or "").strip()
    if not lane:
        return err("that receipt does not name its modality; pass --lane")
    if not lanes.human_judged(lane):
        note(f"note: the {lane} lane has programmatic checks and is not in "
             f"lanes.HUMAN_JUDGED, so this verdict is extra rather than the "
             f"deciding one.")
    pairs = human.pairings(receipt)
    if not pairs:
        return err("no two candidates in that run share a case, so there is "
                   "nothing to compare")
    specs = receipt.get("specs") or {}

    def _record(lane_, pairs_):
        """Write the lane's verdict the moment it becomes decidable."""
        won, why = human.lane_verdict(lane_, pairs_)
        if won is None:
            return
        incumbent = adopt.default_for(lane_, winners.typed().get(lane_, ""))
        names = sorted({p["a"] for p in pairs_} | {p["b"] for p in pairs_})
        store = ms.connect()
        try:
            candidates.from_receipt(store, specs, lane=lane_)
            for challenger in names:
                spec = (candidates.get(store, challenger) or {}).get("spec")
                if not spec:
                    note(f"  not recorded: no stored candidate maps "
                         f"{challenger} to a spec a lane can run")
                    continue
                if incumbent not in (challenger, spec):
                    # Decided on the names the pairs carry, recorded as the
                    # spec, which is what a lane can run. #337.
                    verdict = dataclasses.replace(adopt.decide_by_hand(
                        lane_, incumbent, challenger, pairs_,
                        force=getattr(a, "force", False),
                        all_machines=getattr(a, "all_machines", False),
                        min_votes=getattr(a, "min_votes", adopt.MIN_VOTES),
                        conn=store), challenger=spec)
                    try:
                        adopt.record(store, verdict)
                    except ms.IllegalTransition as exc:
                        note(f"  skipped {exc}")
                    except adopt.Held as exc:
                        note(f"  not adopted: {exc}")
                    else:
                        _say_adopted(store, lane_, verdict)
            store.commit()
        finally:
            store.close()
        note(f"  recorded: {won or 'no preference'} -- {why}")

    # A RUN THAT IS ALREADY JUDGED RECORDS WITHOUT ANYONE CLICKING. Recording
    # only on a new answer leaves a finished run unrecorded forever, and
    # recording only at shutdown loses it whenever the server is killed rather
    # than interrupted -- which is how a service manager stops things.
    _record(lane, pairs)

    try:
        judge_server.serve(lane, receipt, port=a.port,
                           open_browser=not a.no_browser, on_answer=_record,
                           run=adopt_cmd._run_name(run))
    except OSError as exc:
        return err(f"could not serve on port {a.port}: {exc}")
    settled = [p for p in pairs
               if human.decided(lane, p["case"], p["a"], p["b"]) is not None]
    note(f"\n{len(settled)} of {len(pairs)} pairing(s) settled")
    for p in pairs:
        got = human.decided(lane, p["case"], p["a"], p["b"])
        if got is None:
            continue
        note(f"  {p['case']:14} {got or 'no preference'}")

    # THE VERDICT GOES IN THE STORE, or the whole exercise is a page somebody
    # clicked. adopt.record already knows how to write a winner that has no
    # proposal row (#262), so a candidate named on a command line lands the
    # same way one from a sweep does.
    won, why = human.lane_verdict(lane, pairs)
    if won is None:
        note(f"\nnot recorded: {why}")
        emit(lane=lane, settled=len(settled), pairings=len(pairs),
             recorded=False, why=why)
        return 0
    note(f"\n{lane}: {'no preference' if not won else won}")
    note(f"  {why}")
    _record(lane, pairs)           # idempotent; covers a run that was already
    emit(lane=lane, settled=len(settled), pairings=len(pairs),  # fully judged
         recorded=True, winner=won or None, why=why)            # before serving
    return 0


def _report_judge_store(a) -> int:
    """Score what the inspect tier queued and no judge has read. #148 phase 3.

    THE RUNG ABOVE --inspect --from-store. _judge_fits() can only see the Fit
    objects produced in its own process, so a judge has never been able to
    reach the store: after #167 that left real candidates with real verdicts
    and nothing ranking them.

    THE CONTROL RUNS FIRST AND THE TIER REFUSES WITHOUT IT. A judge is a
    metric, this one samples, and a tier that scores unattended on a schedule
    has nobody present to doubt it. `--no-control` exists for a person watching
    the output, never for a Job.
    """
    from harness import judge
    from harness import memory_store as ms

    gateway = getattr(a, "gateway", "") or ""
    try:
        rubric = judge.load()
    except judge.JudgeError as exc:
        return err(str(exc))

    # THE WORK FIRST, THEN THE GATE, and in that order for two reasons. The
    # control costs a model call per control item, so a Job whose queue is
    # empty would otherwise pay eighteen of them to prove a rubric separates
    # and then score nothing. And a store that cannot be reached should be
    # found in the first second rather than after the judging budget is spent:
    # the first run of this tier in a cluster did exactly that, spending its
    # control on a gateway and then dying on a Postgres in recovery.
    store = ms.connect()
    scored = 0
    try:
        rows = ms.judgeable(store, limit=getattr(a, "top", 25))
        rows = discover_cmd.shard(rows, getattr(a, "shard", ""))
        waiting = ms.judgeable_total(store)
        if not rows:
            print("nothing queued by inspect that a judge has not already read")
            return 0

        if not getattr(a, "no_control", False):
            runs = max(1, getattr(a, "runs", 3))
            # THE SHAPE OF ITS OWN INPUT. This tier feeds the judge store
            # rows, so a control made of hand-written project descriptions
            # answers a question about different data -- it separated at +7
            # while every real candidate came back 3/10 (#175).
            shape = getattr(a, "shape", "") or "carded"
            try:
                got = judge.control_repeated(runs=runs, gateway=gateway,
                                             shape=shape)
            except Exception as exc:  # noqa: BLE001
                return err(f"control failed, so nothing was scored: {exc}")
            gaps = ", ".join(f"{g:+d}" for g in got["gaps"])
            print(f"control: rubric {got['rubric']}, judge {got['model']}, "
                  f"shape {got['shape']}, gap per run {gaps}, "
                  f"spread {got['spread']}")
            if not got["separates"]:
                return err(
                    f"the rubric separates in only {got['separated_in']} of "
                    f"{got['runs']} control runs, so nothing was scored. A "
                    f"score from a rubric that does not discriminate is a "
                    f"number, not a ranking")

        print(f"\njudging {len(rows)} candidate(s) the sweep found and the "
              f"source tier answered:")
        for row in rows:
            item = judge.describe(
                # The card first: a sighting's `why` is what one source said
                # on one day, and for a prose-swept id it is usually empty.
                row["name"], why=row.get("description") or row.get("why") or "",
                source=row.get("source") or "", times_seen=row.get("times") or 0,
                relevance=row.get("relevance") or 0,
                inspected=row.get("inspected") or "")
            try:
                score, why = judge.score(item, rubric, gateway=gateway)
            except Exception as exc:  # noqa: BLE001 - one bad reply is not a run
                err(f"{row['name']}: {exc}")
                continue
            print(f"  {score:2d}/10  {row['name']:40.40s} {why[:48]}")
            try:
                ms.decide(store, row["name"], "queued", tier=ms.JUDGE,
                          score=score, rubric=rubric.stamp, judge=rubric.model,
                          detail=why[:200], reason=reasons.CANDIDATE)
            except ms.IllegalTransition:
                continue   # answered by a later tier while this one scored
            scored += 1
    finally:
        store.close()
    left = max(0, waiting - scored)
    print(f"\n{scored} scored, under rubric {rubric.identity} judged by "
          f"{rubric.model}"
          + (f"; {left} still waiting" if left else ""))
    return 0
