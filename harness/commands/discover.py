"""`soh discover`: sweep, feeds, neighbors, sources, inspect, and the reports on what was found."""
from __future__ import annotations

import argparse
import json

from harness import discover as discovery, paths, reasons
from harness.commands.common import err
from harness.commands import judge as judge_cmd
from harness.commands import loop as loop_cmd
from harness.commands import report as report_cmd
from harness.commands import screen as screen_cmd


def cmd_discover(a) -> int:
    """What can this machine do, and what has never been measured?

    Built as a command rather than done by hand because the answer changes
    every time anything is installed or any eval is run. A number in a document
    is wrong by the next commit.
    """
    if getattr(a, "loop", False):
        return loop_cmd._report_loop(a)
    if getattr(a, "sweep", False):
        return _report_sweep(a)
    if getattr(a, "inspect", False):
        return _report_inspect(a)
    if getattr(a, "judge", False) and getattr(a, "from_store", False):
        return judge_cmd._report_judge_store(a)
    if getattr(a, "queue", False):
        return report_cmd._report_queue(a)
    if getattr(a, "screen", False):
        return screen_cmd._report_screen(a)
    if getattr(a, "winners", False):
        return report_cmd._report_winners(a)
    if getattr(a, "coverage", False):
        return report_cmd._report_coverage(a)
    if getattr(a, "neighbors", False):
        return _report_neighbors(a)
    if getattr(a, "control", False):
        return _report_control(a)
    if getattr(a, "recurrence", False):
        return _report_recurrence(a)
    if getattr(a, "revisit", False):
        return _report_revisit(a)
    if getattr(a, "evidence", False):
        return _report_evidence(a)
    if getattr(a, "sources", False):
        return _report_sources(a)
    if getattr(a, "feeds", False):
        return _report_feeds(a)
    if getattr(a, "benchmarks", False):
        return _report_benchmarks(a)
    if getattr(a, "papers", False):
        return _report_papers(a)
    if a.external:
        if not a.lane:
            return err("--external needs a --lane: the registries are asked "
                       "different questions per modality")
        try:
            found = discovery.external(a.lane)
        except ValueError as exc:
            return err(str(exc))
        if a.json:
            print(json.dumps({"candidates": [vars(c) for c in found]}, indent=2))
            return 0
        if not found:
            print("nothing new found. Either this machine has measured what "
                  "the registry knows about, or there is no network.")
            return 0
        print(f"\n{a.lane}: candidates the registry has that nothing here has "
              f"measured")
        print("(proposals, not conclusions -- the eval decides)")
        for c in found:
            print(f"\n  {c.name}")
            print(f"    {c.source}")
            print(f"    {c.note}")
            print(f"    -> uv run python -m evals.run {c.how}")
        return 0

    caps = discovery.annotate(discovery.capabilities())
    if a.lane:
        caps = [c for c in caps if c.lane == a.lane]
    if a.gap:
        # A broken row is not a gap: running the command only refuses.
        caps = [c for c in caps
                if not c.measured and c.present and not c.blocked]

    if a.json:
        print(json.dumps({"capabilities": [vars(c) for c in caps]}, indent=2))
        return 0

    if not caps:
        print("nothing found" if not a.gap else "no gaps: everything here has been measured")
        return 0

    by_lane: dict[str, list] = {}
    for c in caps:
        by_lane.setdefault(c.lane, []).append(c)
    for lane in sorted(by_lane):
        print(f"\n{lane}")
        for c in sorted(by_lane[lane], key=lambda c: (c.measured, c.name)):
            # A recorded decision is not a defect, so it gets its own mark.
            if c.kind == "decision":
                mark = "declined"
            # BROKEN outranks measured: a thing can be measured and broken.
            elif c.blocked:
                mark = "BROKEN"
            elif not c.present:
                mark = "MISSING"
            elif c.measured:
                mark = "measured"
            else:
                mark = "NEVER RUN"
            print(f"  {mark:9} {c.kind:7} {c.name}")
            if c.blocked:
                print(f"            !! {c.blocked}")
            elif not c.present and c.note:
                print(f"            !! {c.note}")
            elif not c.measured:
                print(f"            -> {c.how}")
    # A declined tool is not an unmeasured gap, so it stays out of the ratio.
    countable = [c for c in caps if c.kind != "decision"]
    total, done = len(countable), sum(1 for c in countable if c.measured)
    print(f"\n{done}/{total} measured. The rest have never been run here.")
    _warn_stale_sources()
    return 0


def _warn_stale_sources() -> None:
    """Discovery nobody remembers to run is discovery that does not happen."""
    from harness import feeds

    try:
        stale = [r for r in feeds.staleness() if r["stale"]]
    except Exception:  # noqa: BLE001
        return
    if not stale:
        return
    names = ", ".join(r["name"] for r in stale[:4])
    print(f"\n{len(stale)} discovery source(s) not read in "
          f"{feeds.interval_days()} days: {names}")
    print("  soh discover --feeds     read them now")
    print("  soh discover --sources   when each was last read")


def _report_control(a) -> int:
    """A judge is a metric, and a metric without a control is noise.

    REPEATED, and that is the whole point of this command. The judge samples
    and nothing pins a seed, so one run gave gap +4 and the next +2 on
    identical inputs. control_repeated() was built for that, was tested, and
    nothing called it -- this command went to the single-shot form, so the
    sentence authorising every score in the project came from one draw.
    Issue #172.
    """
    from harness import judge
    runs = max(1, getattr(a, "runs", 3))
    try:
        got = judge.control_repeated(runs=runs, shape=getattr(a, "shape", "")
                                     or "described",
                                     gateway=getattr(a, "gateway", "") or "")
    except Exception as exc:  # noqa: BLE001
        return err(f"control failed: {exc}")
    if a.json:
        print(json.dumps(got, indent=2))
        return 0
    print(f"\nrubric {got['rubric']}, judge {got['model']}, "
          f"shape {got['shape']}, {got['runs']} run(s)")
    for r in got["rows"]:
        print(f"  {r['outcome']:5} {r['score']:2}  {r['name']:20} {r['why'][:52]}")
    gaps = ", ".join(f"{g:+d}" for g in got["gaps"])
    print(f"\n  gap per run {gaps}   spread {got['spread']}")
    if got["separates"]:
        print(f"  SEPARATES in all {got['runs']}. Scores from this rubric may "
              f"be used to rank.")
        return 0
    print(f"  DOES NOT SEPARATE: {got['separated_in']} of {got['runs']} runs. "
          f"No ranking may be drawn from this rubric.")
    return 1


def _report_revisit(a) -> int:
    """Verdicts another machine made whose condition THIS machine now meets.

    A refusal is routinely a fact about one box: `needs-cuda` is true where
    there is no cuda runtime and false where there is, and `too-big` is
    measured against a ceiling that describes one 32 GB machine. Until #266 the reason lived in prose, so
    a verdict made elsewhere was a dead end -- there was no way to ask which
    of them this machine could now answer.
    """
    from harness import memory_store as ms

    store = ms.connect()
    try:
        here = ms.this_machine()
        rows = ms.revisitable(store)
        if getattr(a, "requeue", False) and rows:
            ms.requeue_revisitable(store)
    finally:
        store.close()
    print(f"this machine: {here['fingerprint']}")
    print(f"  runtimes {here['runtimes'] or '-'}, "
          f"ceiling {here['ceiling_gb']:.0f} GiB, "
          f"memory {here['memory_gb']:.0f} GB\n")
    if not rows:
        print("nothing to revisit: no verdict from another machine has a "
              "condition this one satisfies.")
        return 0
    print(f"{len(rows)} candidate(s) refused for a reason that no longer "
          f"applies here:\n")
    for r in sorted(rows, key=lambda r: (r["lane"] or "", r["name"])):
        print(f"  {(r['lane'] or '-'):8} {r['name']}")
        where = r["decided_on"] or "an unrecorded machine"
        print(f"           {r['outcome']} on {where}: "
              f"{(r['detail'] or '')[:70]}")
        print(f"           waiting on {r['until']}, which this machine meets")
    if getattr(a, "requeue", False):
        print(f"\nre-queued {len(rows)} for the inspect tier.")
    else:
        print("\n--requeue sends them back to inspect: a verdict is never "
              "deleted.")
    return 0


def _report_evidence(a) -> int:
    """Verdicts whose receipt is no longer on disk.

    A verdict whose evidence is gone cannot be re-judged. Schema 10 exists
    because verdicts were recorded from runs that never reached a model, and
    undoing those required READING the runs back. That migration ran once and
    nothing has checked since.
    """
    from harness import memory_store as ms

    store = ms.connect()
    try:
        gone = ms.dangling_receipts(store)
        total = store.execute(
            "SELECT COUNT(*) c FROM verdicts WHERE run_path != ''"
        ).fetchone()["c"]
    finally:
        store.close()
    if not gone:
        print(f"every one of the {total} verdicts that names a run can still "
              f"reach it.")
        return 0
    print(f"{len(gone)} of {total} verdicts name a run that is no longer on "
          f"disk, so they cannot be re-judged:\n")
    for r in sorted(gone, key=lambda r: r["name"]):
        print(f"  {r['outcome']:9} {r['tier']:8} {r['name']}")
        print(f"            {r['run_path']}")
    print("\nThese are not deleted: a verdict is a record. They are reported "
          "so a re-judgement is known to be impossible rather than assumed "
          "to be available.")
    return 0


def _report_recurrence(a) -> int:
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        rows = ms.recurrence(conn, minimum=2)
        stats = ms.precision(conn)
        per_source = ms.by_source(conn)
        extract = ms.extraction(conn)
    finally:
        conn.close()
    if a.json:
        print(json.dumps({"recurrence": rows, "totals": stats,
                          "by_source": per_source,
                          "extraction": extract}, indent=2))
        return 0
    if not rows:
        print("nothing seen more than once yet. Run `soh discover --feeds`.")
    else:
        print("\nseen more than once (recurrence beats a single mention):")
        for r in rows:
            span = (r["last_seen"] - r["first_seen"]) / 86400.0
            print(f"  {r['times']}x over {span:5.1f}d  {r['name'][:44]:46}"
                  f" {r['sources']} source(s)")
    print(f"\n{stats['proposals']} proposals, {stats['resolved']} resolved, "
          f"{stats['verdict_measured']} measured, "
          f"{stats['verdict_declined']} declined")
    if per_source:
        print("\nper source (issue #49: precision is a query, not a count):")
        print(f"  {'source':24} {'proposed':>8} {'resolved':>8} {'settled':>8}")
        for r in per_source:
            print(f"  {r['source']:24} {r['proposals']:8d} "
                  f"{r['resolved']:8d} {r['settled']:8d}")
    if extract:
        print("\nextraction precision: of the names pulled out of prose, how "
              "many were real")
        print(f"  {'source':24} {'kept':>6} {'dropped':>8} {'precision':>10}")
        for r in extract:
            reasons = ", ".join(f"{k} {v}" for k, v in
                                sorted(r["reasons"].items(), key=lambda kv: -kv[1]))
            print(f"  {r['source']:24} {r['kept']:6d} {r['dropped']:8d} "
                  f"{r['precision']:10.2f}   {reasons}")
    return 0


def shard(names: list, spec: str) -> list:
    """The slice of the work this worker owns, as `i/n`.

    WITHOUT THIS A FAN-OUT IS FICTION. `parallelism: 4` on a Job whose pods all
    receive the same arguments is four workers doing identical work: four times
    the API budget, four times the clones, one result, and four writers racing
    on the same rows.

    A STRIDE, not a contiguous block. The candidate list arrives ranked, so
    splitting it into blocks would give worker 0 every strong candidate and the
    last worker the tail -- the slowest repos to clone are not evenly spread
    either, and blocks turn that into one straggler. `names[i::n]` interleaves,
    which is both simpler and better balanced.

    Empty spec means the whole list, so the CLI on a laptop is unchanged.
    """
    if not spec:
        return names
    try:
        i, n = (int(part) for part in spec.split("/", 1))
    except ValueError:
        raise SystemExit(f"--shard wants i/n, got {spec!r}")
    if n < 1 or not 0 <= i < n:
        raise SystemExit(f"--shard {spec} is not a slice of {n} workers")
    return names[i::n]


def resolve_registry(name: str, client, model=None) -> tuple[str, dict | None]:
    """Which registry answers for a name nothing wrote a registry down for.

    THE MIGRATION CANNOT ANSWER THIS. A name lifted from prose was resolved
    against HuggingFace by the sweep and the store kept the reddit permalink,
    so 223 of 235 rows carry no evidence either way (#167). Guessing from the
    shape of the string would be free and wrong: an `org/name` is a valid id in
    both namespaces, and a definite 404 is now terminal, so a wrong guess
    settles a real model as missing for good.

    HuggingFace first, on the same argument feeds.candidates() already makes in
    its two passes: where both answer, the model is the thing the eval can run.

    Returns the registry and whatever the answering registry already handed
    over, so the caller does not ask a second time: both of these rate-limit,
    and a repeated question is a request spent on nothing. Raises Gone only
    when BOTH say no; an empty registry means nothing could be told, which
    settles nothing.
    """
    from harness import github, inspect as ins
    from harness import memory_store as ms

    model = model or ins.hf_model
    reachable = False
    try:
        return ms.HUGGINGFACE, model(name)
    except ins.Gone:
        reachable = True
    except ins.InspectError:
        pass
    try:
        return ms.GITHUB, client.repo(name)
    except github.NotFound:
        if reachable:
            raise ins.Gone(f"{name}: neither registry has anything by that name")
    except github.GitHubError:
        pass
    return "", None


def _report_inspect(a) -> int:
    """Read a candidate's source before anyone downloads its weights. #61."""
    from harness import github, inspect as ins
    from harness import memory_store as ms

    client = github.Client(budget=getattr(a, "budget", 900))
    work = paths.home() / "cache" / "clones"
    work.mkdir(parents=True, exist_ok=True)
    store = ms.connect()
    try:
        if a.repos:
            # org/name is valid in both registries, so ask rather than assume:
            # a HuggingFace model named here was cloned from GitHub. #424.
            work_items = [(n, "") for n in a.repos]
        elif getattr(a, "from_store", False):
            # The rung the ladder was missing: what the sweep found, rather
            # than the crowd. Without this the two tiers read different
            # sources and nothing consumes a swept proposal.
            #
            # ASKED OF EACH REGISTRY SEPARATELY. One list handed to one API is
            # how 227 of 235 swept candidates 404ed: every name the sweep
            # writes is a HuggingFace id and this tier only knew how to clone
            # from GitHub. Issue #167.
            limit = getattr(a, "top", 10) * 5
            work_items = [(n, r) for r in ms.REGISTRIES
                          for n in ms.pending(store, limit=limit, registry=r,
                                              screened=False)]
            # And the ones the store cannot route, which it resolves rather
            # than guesses at. See resolve_registry().
            work_items += [(n, "") for n in
                           ms.pending(store, limit=limit, registry="",
                                      screened=False)]
            # CONSUME IN THE CONSUMER'S ORDER. `pending` sorts by corroboration
            # and recency; the fetch tier reads the same queue in rank order,
            # by the value of the information a screen would buy. Two tiers
            # ordering one queue by different keys means the producer sizes
            # rows the consumer will never reach, and both halves look healthy
            # -- RULE #275, and the reason a loop run sized 50 candidates and
            # still fetched nothing. Rows the fetch tier cannot see keep their
            # place at the back rather than being dropped.
            work_items = loop_cmd._in_fetch_order(store, work_items)
        else:
            work_items = [(n.repo, ms.GITHUB) for n in
                          __import__("harness.neighbors", fromlist=["x"])
                          .neighbors(client=client, top=getattr(a, "top", 10))]
        work_items = shard(work_items, getattr(a, "shard", ""))
        out = []
        for repo, registry in work_items:
            card = None
            if not registry:
                try:
                    registry, card = resolve_registry(repo, client)
                except ins.Gone as exc:
                    err(f"{repo}: {exc}")
                    try:
                        ms.decide(store, repo, "broken", tier=ms.INSPECT,
                                  detail=str(exc)[:200], reason=reasons.UPSTREAM)
                    except ms.IllegalTransition:
                        pass   # a later tier already answered it
                    continue
                if not registry:
                    err(f"{repo}: neither registry could be reached, so it "
                        f"stays unanswered")
                    continue
                ms.set_registry(store, repo, registry)
            if registry == ms.HUGGINGFACE:
                try:
                    fit = ins.inspect_model(repo, data=card)
                except ins.Gone as exc:
                    # A definite 404 is an answer about the candidate, so it is
                    # recorded as one. An unreachable registry is not.
                    err(f"{repo}: {exc}")
                    try:
                        ms.decide(store, repo, "broken", tier=ms.INSPECT,
                                  detail=str(exc)[:200], reason=reasons.UPSTREAM)
                    except KeyError:
                        pass   # named on the command line, never proposed
                    except ms.IllegalTransition:
                        pass   # a later tier already answered it
                    continue
                except ins.InspectError as exc:
                    err(f"{repo}: {exc}")
                    continue
            else:
                try:
                    meta = client.repo(repo) if card is None else card
                except github.GitHubError as exc:
                    err(f"{repo}: {exc}")
                    continue
                try:
                    fit = ins.inspect(repo, work, meta=meta)
                except ins.InspectError as exc:
                    err(f"{repo}: {exc}")
                    continue
            out.append(fit)
            ms.record(store, ms.Seen(
                name=repo, source="inspect", registry=registry,
                kind="weights" if registry == ms.HUGGINGFACE else "repo",
                url=(f"https://huggingface.co/{repo}"
                     if registry == ms.HUGGINGFACE
                     else f"https://github.com/{repo}"),
                resolved=repo, lane=fit.lanes.get(repo, ""), why=fit.why,
                lane_source=fit.card.lane_source,
                # WHAT IT IS, beside what the verdict said about it. The judge
                # reads this; with only a name it cannot rank at all (#175).
                description=fit.description))
            ms.set_size(store, repo, fit.largest)
            if ms.set_lane(store, repo, fit.lanes.get(repo, ""),
                           source=fit.card.lane_source):
                print(f"    lane corrected from the card: {repo} "
                      f"-> {fit.lanes[repo]}")
            # The card's facts as columns and lineage rows; readers ask
            # these, never the description. #414.
            ms.set_card(store, repo, fit.card)
            # A thing that cannot run here is ANSWERED, so it is terminal and
            # never proposed again. "unknown" settles nothing, deliberately.
            outcome = {"fits": "queued", "unknown": ""}.get(fit.verdict, "declined")
            if outcome:
                # The tier that read the repo writes why and what would end
                # the wait; nothing re-reads its sentence. #270, #333, #408.
                try:
                    ms.decide(store, repo, outcome, tier=ms.INSPECT,
                              size_bytes=fit.largest if fit.verdict == "fits" else 0,
                              upstream_idle_days=fit.upstream_idle_days,
                              reason=ins.reason_of(fit), until=ins.until_of(fit),
                              detail=f"{fit.verdict}: {fit.why}"[:200])
                except ms.IllegalTransition as exc:
                    print(f"    kept its state: {exc}")
            # The WEIGHTS are what a download queue can act on. The repo is
            # something to install and screen, and the two are not the same
            # queue: queueing the repo sent GitHub names to snapshot_download,
            # which wants a HuggingFace id, and every one of them 401'd.
            if fit.verdict != "fits":
                continue
            if registry == ms.HUGGINGFACE:
                # A model IS the weight, so there is no second queue to fill
                # and nothing to retire: what `queued` means here is already
                # recorded above.
                continue
            # In HEADLINE order, not smallest-first: the smallest named
            # weight is almost always a tokenizer or a helper, and the first
            # queue built that way filled with them. Issue #68.
            ranked = [m for m in fit.headline if m in fit.weights][:3]
            # Re-inspecting CORRECTS the queue rather than only extending it:
            # weights this repo queued under an older ranking, and no longer
            # ranks, are retired. Issue #73.
            ms.retire_unlisted(
                store, repo, keep=ranked, why=(
                    "no longer among this repo's top-ranked weights"))
            for model_id in ranked:
                size = fit.weights[model_id]
                if size > ins.ceiling_bytes():
                    continue
                ms.record(store, ms.Seen(
                    name=model_id, source="inspect", kind="weights",
                    registry=ms.HUGGINGFACE, category=ms.MODEL,
                    url=f"https://huggingface.co/{model_id}",
                    resolved=model_id, lane=fit.lanes.get(model_id, ""),
                    why=f"named by {repo}"))
                ms.set_size(store, model_id, size)
                # THE CARD OVERWRITES A GUESS. record() keeps the first
                # non-empty lane; this one was read off the publisher's own
                # task, so it outranks whatever the sweep inferred. #227.
                if ms.set_lane(store, model_id, fit.lanes.get(model_id, "")):
                    print(f"    lane corrected from the card: {model_id} "
                          f"-> {fit.lanes[model_id]}")
                ms.link(store, repo, model_id, "needs")
                # A sighting never reopens a decided name; decide() refuses. #399.
                try:
                    ms.decide(store, model_id, "queued", tier=ms.INSPECT,
                              size_bytes=size, reason=reasons.CANDIDATE,
                              detail=f"lane={fit.lanes.get(model_id) or '-'} "
                                     f"named by {repo}")
                except ms.IllegalTransition:
                    continue
    finally:
        store.close()
    if getattr(a, "judge", False):
        screen_cmd._judge_fits(out, store_path=None)
    if a.json:
        print(json.dumps({"inspected": [vars(f) for f in out]}, indent=2))
        return 0
    print("\nread from source, with nothing downloaded and nothing run")
    for f in out:
        print(f"\n  {f.verdict.upper():14} {f.repo}")
        print(f"    {f.why}")
        bits = []
        if f.mlx:
            bits.append("MLX-native")
        if f.mps and not f.mlx:
            bits.append("torch/MPS")
        if f.cuda_mentioned:
            bits.append(f"mentions {', '.join(f.cuda_mentioned[:2])}")
        if f.unsized:
            bits.append(f"{len(f.unsized)} weight(s) unsized")
        if bits:
            print(f"    {'; '.join(bits)}")
    return 0


def _report_neighbors(a) -> int:
    """What the people who build what we run are looking at. Issue #58."""
    from harness import feeds, github, memory_store as ms, neighbors as nb

    client = github.Client(budget=getattr(a, "budget", 900))
    try:
        people = nb.cohort(client=client, limit=getattr(a, "crowd", 250))
    except github.GitHubError as exc:
        feeds.record_failure("github-crowd", str(exc))
        return err(f"{exc}. `gh auth status` to check the token.")
    if getattr(a, "control", False):
        got = nb.control(list(nb.DEFAULT_SEEDS), people, client)
        if a.json:
            print(json.dumps(got, indent=2))
            return 0
        print(f"\ncrowd of {got['crowd']}, ranking {len(got['top'])}")
        print(f"  expected and found : {', '.join(got['expected_found']) or 'NONE'}")
        print(f"  expected but absent: {', '.join(got['missing']) or 'none'}")
        print(f"  decoys in the top  : {', '.join(got['decoys_in_top']) or 'none'}")
        print(f"\n  SEPARATES: {got['separates']}")
        if not got["separates"]:
            print("  Do not quote a score from this run.")
        print("\n  by shared count alone, which is what we do NOT ship:")
        for r in got["raw_top"][:5]:
            print(f"    {r}")
        return 0

    found = nb.neighbors(people, client, top=getattr(a, "top", 25),
                         exclude=nb.DEFAULT_SEEDS)
    if a.json:
        print(json.dumps({"crowd": len(people),
                          "neighbors": [vars(n) for n in found]}, indent=2))
        return 0
    print(f"\nrepos concentrated in the crowd that builds what this machine "
          f"runs\n({len(people)} people, {client.spent} requests; a popularity "
          f"signal, not a measurement)")
    if client.stale:
        print(f"  {len(client.stale)} answer(s) served from a stale cache")
    for n in found:
        flag = "  ARCHIVED" if n.archived else ""
        print(f"\n  {n.score:.5f}  {n.repo}{flag}")
        print(f"    {n.shared} of {n.crowd} starred it; {n.stars} stars, "
              f"pushed {n.pushed}")
        if n.description:
            print(f"    {n.description[:100]}")
    # Into the store, so a sighting counts towards recurrence and the graph
    # finally has edges to walk. Seeds are recorded too, because link() needs
    # both ends to exist.
    store = ms.connect()
    try:
        feeds.record_fetch("github-crowd", store=store)
        for seed in nb.DEFAULT_SEEDS:
            ms.record(store, ms.Seen(name=seed, source="installed", kind="repo",
                                     registry=ms.GITHUB,
                                     url=f"https://github.com/{seed}",
                                     resolved=seed))
        for n in found:
            ms.record(store, ms.Seen(name=n.repo, source="github-crowd",
                                     registry=ms.GITHUB,
                                     url=f"https://github.com/{n.repo}",
                                     why=n.description, kind="repo",
                                     relevance=feeds.relevance(
                                         f"{n.repo} {n.description} "
                                         f"{' '.join(n.topics)}"),
                                     resolved=n.repo))
            for seed in nb.DEFAULT_SEEDS:
                ms.link(store, seed, n.repo, "crowd",
                        shared=n.shared, crowd=n.crowd, score=n.score)
        if getattr(a, "judge", False):
            _judge_neighbors(found, store)
    finally:
        store.close()
    return 0


def _judge_neighbors(found, store):
    """Score crowd proposals with the rubric. Same cheapest tier as the feeds.

    A repo card says more than a recap blurb, so the judge is shown the
    description, topics and how much of the crowd starred it.
    """
    from harness import judge
    from harness import memory_store as ms
    try:
        rubric = judge.load()
    except judge.JudgeError as exc:
        return err(str(exc))
    print("\n  judged:")
    for n in found:
        why = f"{n.description} [{n.language}; {', '.join(n.topics[:6])}]"
        row = store.execute(
            "SELECT v.detail FROM verdicts v JOIN proposals p "
            "ON p.id = v.proposal_id WHERE p.name = ? AND v.tier = 'inspect' "
            "ORDER BY v.id DESC LIMIT 1", (n.repo,)).fetchone()
        try:
            score, reason = judge.score(
                judge.describe(n.repo, why=why, source="github-crowd",
                               times_seen=n.shared,
                               inspected=(row["detail"] if row else "")),
                rubric)
        except Exception as exc:  # noqa: BLE001
            err(f"{n.repo}: {exc}")
            continue
        print(f"    {score:2d}/10  {n.repo:38.38s} {reason[:60]}")
        try:
            ms.decide(store, n.repo, "queued", tier=ms.JUDGE, score=score,
                      reason=reasons.CANDIDATE,
                      rubric=rubric.stamp, judge=rubric.model,
                      detail=reason[:200])
        except (KeyError, ms.IllegalTransition):
            pass
    return 0


def _report_sources(a) -> int:
    from harness import feeds

    rows = feeds.staleness()
    proposed = discovery.feed_sources()
    reachable = discovery.lane_reach()
    if a.json:
        print(json.dumps({"sources": rows, "reach": reachable,
                          "proposed": [vars(c) for c in proposed]}, indent=2))
        return 0
    print(f"\ndiscovery sources (interval {feeds.interval_days()} days, "
          f"${feeds.INTERVAL_ENV} to change)")
    for r in rows:
        age = ("never read" if r["age_days"] is None
               else f"{r['age_days']:.1f} days ago")
        mark = "STALE" if r["stale"] else "ok   "
        fails = (f"; {r['failures']} failed read(s) since: {r['last_error'][:80]}"
                 if r.get("failures") else "")
        print(f"  {mark} {r['name']:24} {age}{fails}")
        print(f"        {r['url']}")
    # WHICH LANES CAN BE REACHED AT ALL. Three lanes had no source and nobody
    # could see it, because nothing anywhere asked the question (#240). Read
    # through lanes.serves(), so the four text-served lanes correctly inherit
    # the text sources rather than reading as unreachable.
    print("\nlanes discovery can reach:")
    for lane, how in reachable.items():
        parts = list(how["feeds"])
        if how["registry"]:
            parts.append(f"{how['registry']} registry queries")
        print(f"  {'none ' if not parts else 'ok   '} {lane:8} "
              f"{', '.join(parts) or 'NO SOURCE: this lane can never fill its queue'}")

    if proposed:
        print("\nsources these feeds point at that we do not read:")
        for c in proposed:
            # Probing is the difference between a shortlist and a guess: half
            # of these hosts serve no feed at all. Issue #50. #182 fixed the
            # argument (the URL is in `source`, not `how`); this resolves the
            # host to its feed, which an example article link never is. #183.
            feed, why = feeds.find_feed(c.source)
            mark = "FEED " if feed else "none "
            print(f"  {mark} {c.name:20} {c.note}")
            print(f"        {feed or c.source}")
            print(f"        {why}")
        print(f"\n  Add one to {feeds.config_path()} to start reading it. "
              f"Deliberately manual: a source URL out of untrusted prose "
              f"should need a human nod.")
    return 0


#: Every source family, in the order a sweep reads them. Each entry is the
#: attribute cmd_discover dispatches on, so adding a source family here is the
#: only edit needed to put it in the sweep.
SOURCE_TIERS = ("feeds", "neighbors", "benchmarks", "papers")


def _report_benchmarks(a) -> int:
    """The benchmark tier of a sweep: registries per lane, once per interval. #491."""
    from harness.commands import benchmarks as benchmarks_cmd
    return benchmarks_cmd.sweep_report(a)


def _report_papers(a) -> int:
    """The technique tier of a sweep: HuggingFace daily papers, each a technique. #576."""
    from harness import papers
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        found = papers.sweep(conn, force=bool(getattr(a, "force", False)))
        row = ms.source_row(conn, papers.SOURCE) or {}
    finally:
        conn.close()
    if row.get("last_status") == "failed":
        err(f"{papers.SOURCE}: {row.get('last_error') or 'failed'}")
        return 1
    laned = sum(1 for s in found if s.lane)
    print(f"  {len(found)} paper(s) read, {laned} with a lane"
          if found else "  no day of papers was due")
    return 0


def _report_sweep(a) -> int:
    """Read EVERY source, then report. What "run a discovery" should mean.

    `--feeds` refreshes the eight feeds and leaves github-crowd untouched,
    because only the --neighbors path calls record_fetch for it. So a sweep
    that ran feeds alone left the star graph -- the source measured as this
    project's best, and the one with zero overlap with the feeds -- nine days
    stale while reporting success. Issue #187.
    """
    rc = 0
    for tier in SOURCE_TIERS:
        # Each report reads its own flags off the namespace, so the flag being
        # dispatched on has to be the one that is set.
        flags = {t: t == tier for t in SOURCE_TIERS}
        sub = argparse.Namespace(**{**vars(a), **flags, "sweep": False})
        if not a.json:
            print(f"\n=== {tier} ===")
        rc = cmd_discover(sub) or rc
    return rc


def _report_feeds(a) -> int:
    from harness import memory_store as ms
    store = ms.connect()
    try:
        found = discovery.from_feeds(
            verify=not a.no_verify,
            min_relevance=1 if a.platform else None, store=store,
            comments=getattr(a, "comments", 0),
            mentions=(_mention_extractor()
                      if getattr(a, "comments", 0) and getattr(a, "judge", False)
                      else None))
        if getattr(a, "judge", False):
            found = _judge_proposals(found, store)
    finally:
        store.close()
    if a.json:
        print(json.dumps({"candidates": [vars(c) for c in found]}, indent=2))
        return 0
    broken = [c for c in found if c.blocked]
    for c in broken:
        err(f"{c.name}: {c.blocked}")
    found = [c for c in found if not c.blocked]
    if not found:
        print("nothing new in the feeds, or no network.")
        return 0
    updates = [c for c in found if c.kind == "update"]
    found = [c for c in found if c.kind != "update"]
    if updates:
        print("\nBEHIND on something already installed:")
        for c in updates:
            print(f"  {c.name:12} {c.note}")
            print(f"    -> {c.how}")
    if not found:
        return 0
    print("\ncandidates the community is talking about that nothing here "
          "has measured")
    print("(a popularity signal, not a measurement -- the eval decides)")
    for c in found:
        print(f"\n  {c.name}")
        print(f"    {c.source}")
        print(f"    {c.note}")
        print(f"    -> uv run python -m evals.run {c.how}")
    return 0


def _mention_extractor():
    """The judge, used to read names out of freeform comment prose. #79."""
    from harness import judge
    return lambda text: judge.mentions(text)


def _judge_proposals(found, store):
    """Score, record and re-sort. The cheapest tier: text only, no GPU."""
    from harness import judge
    from harness import memory_store as ms
    try:
        rubric = judge.load()
    except judge.JudgeError as exc:
        err(str(exc))
        return found
    for c in found:
        if c.kind != "proposal":
            continue
        try:
            score, why = judge.score(
                judge.describe(c.name, why=c.note, relevance=c.relevance),
                rubric)
        except Exception as exc:  # noqa: BLE001
            err(f"{c.name}: {exc}")
            continue
        c.relevance = score
        c.note = f"[{score}/10] {why[:90]} | {c.note}"
        try:
            ms.decide(store, c.name, "queued", tier="judge", score=score,
                      rubric=rubric.stamp, judge=rubric.model, detail=why[:200],
                      reason=reasons.CANDIDATE)
        except (KeyError, ms.IllegalTransition):
            pass
    found.sort(key=lambda c: -getattr(c, "relevance", 0))
    return found
