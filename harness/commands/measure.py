"""The measure tier, verify and throughput: run a candidate's cases and settle what they say."""
from __future__ import annotations

import contextlib
import json
import math
import time
from dataclasses import dataclass, replace
from pathlib import Path

from evals import watch
from harness import lanes, methods, paths, reasons
from harness.commands.common import emit, err, note
from harness.commands import jobs as jobs_cmd

#: The watchdog criteria whose pause frees memory rather than asking the sweep to stop. #1082.
MEMORY_PAUSES = ("memory", "memory_warn")


def cmd_verify(a) -> int:
    """Establish that each lane works, by running its own default. #234."""
    import contextlib
    import subprocess

    from harness import report, verify
    from harness.commands.common import lent_store

    # Without --run it only says what it would: read-only, on one lent connection. #1432.
    with contextlib.nullcontext() if getattr(a, "run", False) else lent_store():
        state = report.state()
        tasks = verify.plan(state["lanes"], only=getattr(a, "lane", ""),
                            force=getattr(a, "all", False))
    if not tasks:
        # NOT "every lane has a receipt". A parked lane has none and is
        # excluded from the plan by design, so saying so here would report a
        # decision as a measurement -- the exact confusion #244 removed from
        # the report a few lines away.
        parked = [l for l in state["lanes"] if l.get("parked")]
        note("every lane that should run here has a recent receipt")
        for l in parked:
            note(f"  {l['lane']} is parked and was not run: {l['parked']}")
        emit(planned=[], parked={l["lane"]: l["parked"] for l in parked})
        return 0

    runnable = [t for t in tasks if not t.skip]
    budget = sum(t.cost_s for t in runnable)
    note(f"\n{len(runnable)} lane(s) to verify, roughly {budget // 60}m "
         f"{budget % 60}s in total:\n")
    for t in tasks:
        note(f"  {t.lane:8} {t.candidate[:40]:40} "
             f"{t.skip or f'~{t.cost_s}s'}")
        note(f"           {t.why}")
    if not getattr(a, "run", False):
        note("\n--run to spend it. Nothing is downloaded either way.")
        emit(planned=[jobs_cmd._task_row(t) for t in tasks], ran=False)
        return 0

    rc = 0
    results = []
    for t in runnable:
        # Its own directory, read back from the store by that name. #410.
        out = paths.new_run(t.lane)
        argv = t.argv + ["--out", str(out)]
        note(f"\n=== {t.lane} ===\n    {' '.join(argv)}", flush=True)
        proc = subprocess.run(argv, capture_output=True, text=True)
        data = _receipt_at(out) or {}
        got = verify.verdict(data, t.lane) if proc.returncode == 0 else "broken"
        line = (verify.summarise(t.lane, data) if proc.returncode == 0
                else (proc.stderr.strip().splitlines() or ["no stderr"])[-1])
        results.append((t.lane, got, line))
        note(f"    {got.upper()}: {line[:150]}")
        if got == "broken":
            rc = 1
    note("\n=== what the lanes do ===")
    for lane, got, _ in results:
        note(f"  {got:8} {lane}")
    emit(ok=rc == 0, planned=[jobs_cmd._task_row(t) for t in tasks], ran=True,
         results=[{"lane": l, "verdict": g, "summary": s_}
                  for l, g, s_ in results])
    return rc


def _ttft_pair(p50, p95) -> str:
    from harness.report import ttft_text
    return ttft_text(p50, p95)


def _load_pair(pair) -> str:
    return "/".join("-" if x is None else f"{x:.1f}" for x in (pair or [None, None]))


def cmd_throughput(a) -> int:
    """How much faster a text spec goes with several requests in flight. #310."""
    import contextlib
    import json as _json
    from harness import exclusive, knobs, serving, throughput, vllm
    code = getattr(a, "code", None)
    if not a.texts and not a.claims and not code:
        return err("throughput needs --texts, --claims or --code")
    texts: list = []
    if code:
        texts = throughput.code_requests(throughput.spread(throughput.code_cases(code), a.n))
    for path in ([a.texts] if a.texts else a.claims or []):
        try:
            rows = [_json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        except (OSError, ValueError) as exc:
            return err(f"cannot read {path}: {exc}")
        texts += (throughput.claims_requests(rows) if not a.texts
                  else [str(r.get(a.field) or "") for r in rows])
    texts = texts[: a.n]
    if a.max_tokens is None:
        from harness import completion
        lane = "code" if code else "claims" if a.claims and not a.texts else ""
        a.max_tokens = completion.BUDGET.get(lane, completion.MAX_TOKENS)
    levels = tuple(int(x) for x in a.levels.split(",") if x.strip())
    serve = getattr(a, "serve", None)
    try:
        where = serving.route(a.model, a.gateway)
        engine = serve or serving.engine_for(a.model)
    except ValueError as exc:
        return err(str(exc))
    if serve and not a.model.startswith(serving.VLLM_PREFIX):
        return err(f"--serve starts a vLLM server; --model must be "
                   f"{serving.VLLM_PREFIX}<repo id>, not {a.model}")
    from harness import models
    models.warn(a.model)
    note(f"{models.display(a.model)} on {engine}: {len(texts)} texts at {levels} in flight, "
         f"max_tokens {a.max_tokens}", flush=True)
    pid = getattr(a, "server_pid", None)
    timeout = getattr(a, "timeout", 300.0)
    # The sweep's own bound, plus the vLLM start it waits for first. #775.
    bound = throughput.deadline_s(len(texts), levels, timeout) + (
        knobs.resolve("harness/vllm.py:served(timeout)") if serve else 0.0)
    with exclusive.held("eval", deadline_s=bound), contextlib.ExitStack() as stack:
        if serve:
            port = int(where.base.rsplit(":", 1)[1])
            note(f"  starting {serve} on port {port}", flush=True)
            srv = stack.enter_context(vllm.served(
                vllm.argv(serve, where.model, port), port,
                log=paths.home() / "logs" / f"{serve}-{port}.log"))
            pid = srv.proc.pid
        got = throughput.sweep(
            where.model, texts, levels=levels, max_tokens=a.max_tokens,
            gateway=where.base, timeout=timeout,
            footprint=(lambda: throughput.footprint_tree(pid)) if pid else None)
    if got and "warmup_s" in got[0]:
        note(f"  warm-up {got[0]['warmup_s']:.2f}s, not counted"
             f"{'' if got[0]['warmup_ok'] else ' (FAILED)'}", flush=True)
    base = got[0]["per_hour"] or 1
    for r in got:
        peak = r.get("peak_bytes")
        note(f"  {r['concurrency']:2d} in flight  {r['per_hour']:7.1f}/h  "
             f"x{r['per_hour'] / base:.2f}  {r.get('tokens_per_s', 0):7.1f} tok/s  "
             f"p50 {r['p50_s']:6.2f}s  p95 {r['p95_s']:6.2f}s  "
             f"ttft {_ttft_pair(r.get('ttft_p50_s'), r.get('ttft_p95_s'))}  "
             f"first {_ttft_pair(r.get('first_token_p50_s'), r.get('first_token_p95_s'))}  "
             f"peak {'-' if peak is None else f'{peak / 1024 ** 3:.1f} GiB'}  "
             f"errors {r['errors']}  truncated {r.get('truncated', 0)}  "
             f"schema {r.get('schema_valid', 0)}/{r.get('schema_checked', 0)}  "
             f"code {r.get('code_passed', 0)}/{r.get('code_checked', 0)}  "
             f"load {_load_pair(r.get('load_avg'))}  "
             f"tokens {r['completion_tokens']}", flush=True)
        for why, n in (r.get("error_kinds") or {}).items():
            note(f"      {n} x {why}", flush=True)
    emit(model=a.model, engines={a.model: engine}, max_tokens=a.max_tokens, levels=got)
    return 0


def cmd_reuse_replay(a) -> int:
    """Replay a paused paired run with the incumbent's draws from earlier matching runs; exit 1 when the verdict moves. #1094."""
    import sqlite3

    from harness import ledger, reuse
    from harness import memory_store as ms
    if a.store:
        conn = sqlite3.connect(f"{Path(a.store).resolve().as_uri()}?immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
    else:
        conn = ledger.open_ro(ms.db_path())
    try:
        got = reuse.replay(conn, a.run)
    except ValueError as exc:
        return err(str(exc))
    finally:
        conn.close()
    note(f"run {got['run_id']} ({got['lane']}): {got['challenger']} against {got['incumbent']}")
    note(f"  matching earlier runs: {got['matching_runs'] or 'none'}; {got['reused']} incumbent cell(s) "
         f"reused ({', '.join(f'run {k}: {v}' for k, v in got['runs'].items()) or '-'}), {got['fresh']} fresh")
    for name in ("control", "replay"):
        note(f"  {name}:")
        for line in got[name]["looks"]:
            note(f"    {line}")
    was, now = got["control"]["verdict"], got["replay"]["verdict"]
    same = _same_verdict(was, now)
    note(f"  {'same verdict' if same else 'VERDICT MOVED'}: control "
         f"{(was or {}).get('decision', 'no verdict')}, replay {(now or {}).get('decision', 'no verdict')}")
    emit(**got, same=same)
    return 0 if same else 1


def _same_verdict(was: dict | None, now: dict | None) -> bool:
    """Both walks reached the same adopt and decision, or neither reached one. #1404."""
    if was is None or now is None:
        return was is None and now is None
    return (was["adopt"], was["decision"]) == (now["adopt"], now["decision"])


def measurable(store, top: int, want: str = "", top_knob: str = "discover_top") -> list[dict]:
    """Survivors in the scoped lane, filtered before the limit; a limit that drops one is a cut. #386, #1087."""
    from harness import cuts
    from harness import memory_store as ms
    every = ms.survivors(store, limit=1_000_000, limit_knob="harness/commands/measure.py:measurable->ms.survivors(limit)")
    rows = [r for r in every if takes(r, want)]
    return cuts.take(rows, top, top_knob, "measurable survivors past --top", conn=store)


def takes(row: dict, want: str = "") -> bool:
    """Whether the measure step may plan `row`: in the scoped lane if any, and only where its method runs. #386, #1134."""
    name = row.get("name", "")
    if want and not methods.serves(name, row.get("lane"), want):
        return False
    return methods.runs_in(name, lane_for(row, want))


def resume_first(store, fresh: list[dict], want: str = "") -> list[dict]:
    """Paused measurements before anything new, each once. #813."""
    from harness import paused
    held = [r for r in ({"name": p["proposal"] or p["challenger"], "lane": p["lane"]} for p in paused.waiting(store))
            if takes(r, want)]
    names = {r["name"] for r in held}
    return held + [r for r in fresh if r.get("name") not in names]


def room_for(row: dict) -> tuple[bool, float | None, str]:
    """(fits now, GB its load needs or None, why) for one queued measurement, by the screen's headroom check. #1082."""
    from harness import candidates, memory, runs
    name = row.get("name", "")
    target = methods.weights_of(name) if methods.is_method(name) else name
    if not target:
        return True, None, f"{name}: its size is unknown; proceeding unchecked"
    with runs.store() as store:
        try:
            spec = candidates.for_proposal(store, lanes.canonical(row.get("lane")), name,
                                           row.get("attaches_to") or "") or ""
        except Exception:  # noqa: BLE001 - an unbuildable spec is priced by its weights alone
            spec = ""
    need = memory.need_gb(target, spec=spec, parallel=1)
    ok, why = memory.check_model(target, spec=spec, parallel=1)
    return ok, need if isinstance(need, (int, float)) else None, why


def lane_for(row: dict, want: str = "") -> str:
    """The lane `row` is measured in: a repo row's own, else the scoped lane when it can run there, else its filed lane. #207, #889, #1134."""
    from harness import repo_gate
    want = (want or "").strip().lower()
    if lanes.canonical(row.get("lane")) == repo_gate.GATE:
        return repo_gate.GATE
    if want and methods.serves(row.get("name", ""), row.get("lane"), want):
        return want
    return lanes.canonical(row.get("lane"))


def _measure_and_adopt(a, row: dict, sweep=None) -> int:
    """_measure, then unload the challenger it loaded. #444."""
    from harness import mlx_server, router
    loaded: list[str] = []
    try:
        return _measure(a, row, loaded, sweep)
    finally:
        for spec in loaded:
            router.release_spec(spec, f"measured {row['name']}")
            mlx_server.release_spec(spec, f"measured {row['name']}")


def _measure(a, row: dict, loaded: list, sweep=None) -> int:
    """One challenger against the lane's incumbent, then the verdict.

    PAIRED AND IN ONE RUN. Both candidates see the same cases, the same repeat
    count and the same machine, so the only axis that moved is the candidate.
    Two separate runs would be two receipts that comparable() would refuse, and
    rightly.
    """
    from harness import adopt, candidates, paused, screen, winners
    from harness import memory_store as ms

    name = row["name"]
    lane = lane_for(row, getattr(a, "lane", ""))
    if not methods.runs_in(name, lane):
        print(f"  {name}: its method does not run the {lane} lane, so it is not measured there (#1134)", flush=True)
        return 0
    store = ms.connect()
    try:
        spec = candidates.for_proposal(store, lane, name,
                                       row.get("attaches_to") or "")
    finally:
        store.close()
    if not spec:
        return err(f"{name}: screened in the {lane} lane and no candidate "
                   f"spec can be built for it")
    incumbent = adopt.default_for(lane, winners.typed().get(lane, ""))
    if not incumbent:
        print(f"  {name}: the {lane} lane has no incumbent to beat, so there "
              f"is nothing to compare against. Measure it on its own first.")
        return 0
    inc_spec = screen.candidate_for(lane, incumbent) or incumbent
    zero = _zero_pass(lane, inc_spec)
    if zero:
        taken = take_measured(lane, inc_spec, zero)
        if taken is not None:
            incumbent, zero = taken.challenger, None
            inc_spec = screen.candidate_for(lane, incumbent) or incumbent
    if spec == inc_spec:
        # An adopted winner is the incumbent; measuring it against itself
        # wrote `declined` for the lane's own default. #393.
        print(f"  {name}: already the {lane} lane's default ({spec})")
        _settle(name, "measured", f"{lane}: already the lane's default")
        return 0
    unscreened = _screen_refusal(a, lane, spec)
    if unscreened:
        if sweep is None:
            return err(f"{name}: not measured: {unscreened}")
        print(f"  {name}: not measured: {unscreened}", flush=True)
        sweep.lines.append(f"{name}: not measured: {unscreened}")
        return 0
    # THE PAIR MUST REACH THE SAME SERVER. One --gateway serves the whole run,
    # so when the challenger's repo id sends it to mlx_lm.server the incumbent
    # cannot travel as a LiteLLM alias: :8081 has never heard of `q3-4b`, the
    # control scored 0 of 27, and the run had nothing to compare against. The
    # config maps every alias to the upstream behind it. #223.
    if screen.routed_gateway(name):
        upstream = screen.upstream_of(incumbent)
        if upstream:
            inc_spec = screen.candidate_for(lane, upstream) or upstream
    split, plan = _plan(a, lane, inc_spec, spec, sweep=sweep)
    held, ident = _held(lane, inc_spec, spec, split, name, sweep)
    if held:
        # A resume runs the exam it started: the stored plan's repeat and side, this sweep's slice. #813.
        plan = _resumed_plan(held["plan"], plan) if held.get("plan") is not None else _recovered_plan(held, plan)
    blank = None if held else adopt.undecidable(lane, inc_spec, spec, plan, split)
    if blank is not None:
        print(f"\n  {lane}: {name} against {incumbent}: not run, {blank.why}", flush=True)
        _record_unrun(blank, spec)
        return 0
    if sweep is not None and sweep.remaining() <= 0:
        print(f"  {name}: not started, the sweep ceiling is reached; it waits for the next sweep", flush=True)
        return 0
    started, spans = time.time(), 1
    while True:
        for _ in range(2):
            # NAME THE DIRECTORY, DO NOT GUESS AT IT AFTERWARDS: a newest-receipt read
            # took a stranger's run (`legacy-...` sorts above timestamps). #222.
            out = (Path(held["out"]) if held else paths.home() / "runs"
                   / f"{time.strftime('%Y%m%d-%H%M%S')}-adopt-{lane}")
            if (getattr(plan, "reuse", None) or {}).get("reused"):
                from harness import reuse
                reuse.write(out, inc_spec, plan.reuse)
            part, last = _slice(plan, time.time() - started)
            argv = _argv(lane, part, out, inc_spec, spec, resume=bool(held),
                         unscreened=lane == "repo")
            # ROUTE IT THE WAY THE SCREEN DOES: LiteLLM refuses a repo id it has no alias for. #223, #206.
            route = screen.routed_gateway(name)
            if route:
                argv += ["--gateway", route]
            print(f"\n  {lane}: {name} against {incumbent}")
            print(f"    {' '.join(argv)}", flush=True)
            if spec not in loaded:
                loaded.append(spec)
            proc = _launch(argv, deadline_s=part.deadline_s)
            if proc.returncode == watch.STALE and held:
                _stale(held, "the run's own checkpoint is another exam", name, sweep)
                held = None
                continue
            break
        if not (getattr(proc, "timed_out", False) or proc.returncode == watch.PAUSED):
            break
        before = int((held or {}).get("done") or 0)
        between = _between_looks(proc, out, last, before)
        rc = _paused(name, lane, inc_spec, spec, split, plan, out, held, ident, sweep,
                     interim=between, spans=spans)
        spans = 0
        if not between:
            return rc
        store = ms.connect()
        try:
            held = paused.find(store, lane, spec)
        finally:
            store.close()
        if held is None:
            return rc
        held = {**held, "identity": ident}
    if _signalled(proc.returncode) and watch.stop_reason(out) == watch.OVERRUN:
        return _ended(name, held, out, sweep)
    if _signalled(proc.returncode) and (watch.read(out) or ({}, []))[1]:
        # Stopped from outside (the watchdog, a TERM): its rows are kept and the next sweep resumes it. #864.
        print(f"    stopped by a signal (exit {proc.returncode}); its checkpointed cases are kept", flush=True)
        return _paused(name, lane, inc_spec, spec, split, plan, out, held, ident, sweep)
    if proc.returncode != 0:
        err(proc.stderr.strip()[-400:] or "no stderr")
        return 1
    taken = (held or {}).get("looks") or []
    if held and held.get("id") is not None:
        # The run finished; whatever is read from it next, nothing is left to resume.
        _settle_pause(held["id"], "done", f"finished after {len(taken)} pause(s)")
    data = _receipt_at(out)
    if not data:
        return err(f"{name}: the run stored no receipt for {out}, so nothing "
                   f"can be adopted from it")
    summary = data.get("summary") or {}
    rows = data.get("rows") or []
    # The run's own specs map is the mapping; store it, then read keys back.
    store = ms.connect()
    try:
        candidates.from_receipt(store, data.get("specs") or {}, lane=lane,
                                proposals={spec: name})
        inc_key = candidates.key_for(store, inc_spec)
        ch_key = candidates.key_for(store, spec)
        rows, summary, taken_from = _merge_reused(store, out, plan, rows, summary, inc_key)
    finally:
        store.close()
    inc_row = _summary_row(summary, inc_key)
    ch_row = _summary_row(summary, ch_key)
    # ASSERT THE RUN IS THE ONE THAT WAS ASKED FOR. Naming the directory stops
    # the loop reading a stranger's receipt; this stops it reading a receipt
    # that is its own and yet describes a different exam, which a crashed or
    # partially-skipped candidate produces. #222.
    if len(summary) and not (inc_row or ch_row):
        return err(f"{name}: the receipt at {out} names {sorted(summary)!r} "
                   f"and neither candidate this run asked for, so it does not "
                   f"describe the run that was just made")
    if not inc_row:
        # THE INCUMBENT IS THE CONTROL. A candidate measured beside a control
        # that did not run says nothing about the candidate, which is the
        # lesson the tts lane already paid for (#194/#195). Name it as the
        # control rather than as a missing summary key: a 15-minute run that
        # ends in "the summary names [...]" makes the reader go looking in the
        # receipt for a spelling problem. Issue #214.
        return err(f"{name}: the incumbent {incumbent} contributed no rows, so "
                   f"this run has no control and nothing can be concluded from "
                   f"it. The summary names {sorted(summary)!r}")
    if not ch_row:
        return err(f"{name}: the challenger contributed no rows. The summary "
                   f"names {sorted(summary)!r}")
    # A CANDIDATE THAT NEVER RAN IS NOT A CANDIDATE THAT LOST. Every row a
    # harness refusal means the request never reached a model, and handing
    # that to adopt.decide dresses a routing failure as a quality result.
    # The rows carry the runner's failure class. #223, #408.
    # THE CONTROL MUST HAVE RUN. This is the general form of the refusal check
    # below, and it catches every variant of "the request never reached a
    # model" without anyone having to classify it first: a 404 from a
    # doubled /v1 got past the phrase list, both candidates scored 0/27, and
    # the loop reported "does not beat the incumbent on the lane's metric".
    # A candidate measured beside a control that passed nothing says nothing
    # about the candidate. #223, and the lesson the tts lane paid for in #194.
    if not int(inc_row.get("passed") or 0) and not zero:
        return err(f"{name}: the incumbent {incumbent} passed "
                   f"0 of {inc_row.get('total') or '?'}, so this run has no "
                   f"working control and nothing can be concluded from it. "
                   f"Fix the lane before reading the challenger.")
    refused = _all_refused(rows, ch_row.get("candidate") or name)
    if refused:
        store = ms.connect()
        try:
            ms.decide(store, name, "queued", tier=ms.SCREEN,
                      detail=f"not measured: {refused}",
                      run_id=data.get("run_id"), reason=reasons.HARNESS)
        except (KeyError, ms.IllegalTransition):
            pass      # measured by hand, never proposed; the report still stands
        finally:
            store.close()
        return err(f"{name}: every case was refused before it reached a model "
                   f"({refused}). The incumbent passed, so this says nothing "
                   f"about the candidate and it stays queued.")
    if zero:
        from harness import baseline
        verdict = baseline.screened(lane, incumbent, spec, ch_row, zero)
        print(f"    kept the incumbent: {verdict.why}", flush=True)
        _record(verdict, spec, data.get("run_id"), out)
        take_measured(lane, inc_spec, zero)
        return 0
    store = ms.connect()
    try:
        tested = adopt.comparisons(store, lane, split.version) if split is not None else 0
        screened = adopt.screened_cases(store, lane, (ch_key, spec))
    finally:
        store.close()
    spent = taken[-1]["spent"] if taken else 0.0
    verdict = adopt.decide(lane, inc_row, ch_row, rows, split=split, plan=plan, spec=spec,
                           tested=tested, alpha=adopt.alpha_for(tested) - spent if taken else None)
    verdict = _confirmed(verdict, rows, split, screened, _served(lane), inc_spec, spec, plan)
    if taken:
        verdict = replace(verdict, evidence={**verdict.evidence, "looks": taken})
    if taken_from:
        verdict = replace(verdict, evidence={**verdict.evidence, "reuse": taken_from})
    print(f"    {'ADOPTED' if verdict.adopt else 'kept the incumbent'}: "
          f"{verdict.why}")
    _record(verdict, spec, data.get("run_id"), out)
    return 0


def _plan(a, lane: str, inc_spec: str, spec: str = "", sweep=None):
    """The lane's split and the repeat the paired gate needs on its holdout; this sweep's slice of it. #479, #591, #673, #806, #813."""
    from dataclasses import replace

    from evals.run import STOCHASTIC_MODALITIES
    from harness import adopt, holdout, power
    from harness import memory_store as ms

    split = holdout.for_lane(lane)
    settings = _settings(lane, inc_spec, spec)
    store = ms.connect()
    try:
        draws, median_s, calls, est = priced(store, lane, inc_spec, spec)
        alpha = adopt.alpha_for(adopt.comparisons(store, lane, split.version))
    finally:
        store.close()
    estimated = ""
    if est["incumbent_source"] == "estimated":
        estimated = (f"seconds per call estimated at {est['incumbent_s']:.0f}s: no incumbent "
                     f"receipt on this machine at the {settings[0]}-token reply budget, so every "
                     f"reply is assumed to spend it at {est['decode_tok_s']:.0f} tok/s")
    elif est["incumbent_source"] == "bounded":
        estimated = (f"seconds per call {est['incumbent_basis']}: no incumbent receipt on this "
                     f"machine at the {settings[0]}-token reply budget")
    rates, seen = power.rates_from(draws, split.holdout)
    effect = getattr(a, "effect", None) or power.effect_for(lane)
    explicit = getattr(a, "repeat", None)
    plan = power.plan([rates[c] for c in split.holdout], effect,
                      stochastic=lane in STOCHASTIC_MODALITIES,
                      repeat=explicit, observed=seen, alpha=alpha,
                      unmeasured=not any(draws.values()),
                      rho=power.icc([list(draws.values())]))
    per = float(getattr(a, "power_budget_min", None) or power.BUDGET_MIN) * 60
    left = sweep.remaining() if sweep is not None else None
    budget = per if left is None else min(per, left)
    every = len(set(split.dev) | set(split.holdout))
    full = power.projected_seconds(every, plan.repeat, median_s, calls)
    side, dev_skipped = "all", ""
    if split.dev and full is not None and full > per:
        side = "holdout"
        dev_skipped = (f"dev: not run, dev and holdout at repeat {plan.repeat} would "
                       f"take {power._hm(full)}, over the {power._hm(per)} budget")
    plan = power.within_budget(
        plan, [rates[c] for c in split.holdout],
        cases_run=every if side == "all" else len(split.holdout), median_s=median_s,
        budget_s=per, explicit=bool(explicit), calls=calls)
    plan = _with_reuse(plan, lane, inc_spec, est, side, spec)
    estimated = "; ".join(x for x in (estimated, power.challenger_note(est)) if x)
    # Longer than one budget is paused and resumed, never refused for length. #813.
    sweeps = (math.ceil(plan.projected_s / per) if plan.projected_s and per else None)
    spans = (f"projected {sweeps} sweep(s) at {power._hm(per)} each, paused and resumed"
             if sweeps and sweeps > 1 else "")
    plan = replace(plan, side=side, dev_skipped=dev_skipped, estimate=est, budget_s=budget,
                   odds=power._cell_odds([rates[c] for c in split.holdout], plan.effect)
                   if split.holdout else None, sweeps=sweeps,
                   why="; ".join(x for x in (spans, plan.why, power.unseen_note(draws), estimated) if x))
    plan = replace(plan, deadline_s=power.deadline(plan))
    print(f"    power: repeat {plan.repeat} over {len(split.holdout)} holdout "
          f"case(s) gives {plan.power:.2f} to detect +{plan.effect:.2f} at "
          f"alpha {plan.alpha}{'; ' + plan.why if plan.why else ''}"
          f"{'; ' + split.caveat if split.caveat else ''}", flush=True)
    if plan.projected_s is not None:
        print(f"    time: {plan.cases_run} case(s) x repeat {plan.repeat} x {calls} "
              f"call(s) projected at {power._hm(plan.projected_s)}; this slice pauses at "
              f"{power._hm(plan.budget_s)}", flush=True)
    if dev_skipped:
        print(f"    {dev_skipped}", flush=True)
    from harness import reuse
    if reuse.line(plan.reuse):
        print(f"    reuse: {reuse.line(plan.reuse)}", flush=True)
    elif (plan.reuse or {}).get("unresolved"):
        print(f"    reuse: none, the incumbent's identity is unreadable: {'; '.join(plan.reuse['unresolved'])}",
              flush=True)
    missing = power.unmeasured(draws, split.holdout)
    if missing and any(draws.values()):
        print(f"    projected: {len(missing)} of {len(split.holdout)} holdout "
              f"unmeasured, drawn from the incumbent's measured per-case rates",
              flush=True)
    return split, plan


def _settings(lane: str, inc_spec: str, spec: str = "") -> tuple[int, tuple]:
    """(reply budget, ladder) the paired evals.run of `inc_spec` and `spec` asks at, as that run derives it. #1352."""
    from evals import run
    return run.run_budget(lane, None, [s for s in (inc_spec, spec) if s]), ()


def priced(store, lane: str, inc_spec: str, spec: str):
    """(incumbent draws, mean seconds per call, calls per case, estimate) for one paired run here; the queue order prices with it too. #696, #1315."""
    from harness import candidates, power, runs
    settings = _settings(lane, inc_spec, spec)
    machines = runs.here(store)
    draws, inc_s = power.served_profile(store, lane, inc_spec, settings, machines)
    basis = ""
    if inc_s is None and settings[0]:
        inc_s, basis = power.served_bound(store, lane, inc_spec, settings, machines)
    median_s, calls, est = power.pair_cost(store, lane, incumbent=candidates.key_of(inc_spec) or inc_spec,
                                           incumbent_spec=inc_spec, incumbent_s=inc_s, challenger=spec,
                                           settings=settings, machines=machines, incumbent_basis=basis)
    return draws, median_s, calls, est


def _stored_cells(lane: str, inc_spec: str, spec: str, side: str, repeat: int) -> dict:
    """reuse.plan of the incumbent's cells on `side` that stored draws under its identity cover. #1094."""
    from evals import run
    from harness import holdout, reuse
    from harness import memory_store as ms
    try:
        cases = run.load_selected(run.parse_args(["--modality", lane]))
    except SystemExit as exc:
        return {"digest": "", "unresolved": [f"cases: {exc}"]}
    on = holdout.only(cases, side)
    ident = run.content_identity(lane, inc_spec, _settings(lane, inc_spec, spec)[0], (), {}, on)
    if not ident["digest"]:
        return {"digest": "", "unresolved": ident["unresolved"]}
    cells = [c.id for c in run.expand_cases(on, repeat)]
    store = ms.connect()
    try:
        return reuse.plan(store, lane, ident["digest"], cells, cases=ident["cases"], parts=ident["parts"])
    finally:
        store.close()


def _with_reuse(plan, lane: str, inc_spec: str, est: dict, side: str, spec: str = ""):
    """The plan with the incumbent cells stored draws under its identity cover, priced without them. #1094."""
    got = _stored_cells(lane, inc_spec, spec, side, plan.repeat)
    if not got["digest"]:
        return replace(plan, reuse=got)
    total = got["reused"] + got["fresh"]
    inc = (est.get("incumbent_s") or 0.0) * (est.get("incumbent_calls") or 1)
    ch = (est.get("challenger_s") or 0.0) * (est.get("challenger_calls") or 1)
    share = inc / (inc + ch) if inc + ch else 0.5
    saved = share * got["reused"] / max(total, 1)
    projected = plan.projected_s * (1 - saved) if plan.projected_s is not None else None
    return replace(plan, reuse=got, projected_s=projected)


#: Seconds a stopped run's process group gets between SIGTERM and SIGKILL. #673.
STOP_GRACE_S = 30.0


@dataclass(frozen=True)
class Launched:
    returncode: int | None
    stderr: str
    timed_out: bool
    elapsed_s: float


def _launch(argv, deadline_s: float | None = None, cwd: str | None = None,
            grace_s: float = STOP_GRACE_S, lock: str = "eval") -> Launched:
    """Take `lock`, then run argv as its own process group; past `deadline_s` stop the whole group. #673, #696."""
    from harness import heartbeat

    with heartbeat.held(lock, deadline_s, say=lambda m: print(f"    {m}", flush=True)):
        return _run_group(argv, deadline_s, cwd, grace_s)


def _run_group(argv, deadline_s, cwd, grace_s) -> Launched:
    import subprocess
    import sys

    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
             if sys.platform == "win32" else {"start_new_session": True})
    started = time.monotonic()
    with _term_raises() as term:
        term.hold()
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, **group)
        try:
            term.release()
            _, stderr = proc.communicate(timeout=deadline_s)
        except subprocess.TimeoutExpired:
            _stop_group(proc, grace_s)
            _, stderr = proc.communicate()
            return Launched(proc.returncode, stderr or "", True, time.monotonic() - started)
        except BaseException:
            _stop_group(proc, grace_s)
            proc.communicate()
            raise
    return Launched(proc.returncode, stderr or "", False, time.monotonic() - started)


class _Term:
    """While held, a SIGTERM waits for release(), so one landing inside Popen cannot orphan the child. #1073."""

    def __init__(self):
        self.held, self.pending = False, 0

    def hold(self):
        self.held = True

    def release(self):
        self.held = False
        if self.pending:
            raise SystemExit(128 + self.pending)


@contextlib.contextmanager
def _term_raises():
    """SIGTERM unwinds instead of killing outright, so the eval's own session is stopped with us. #805."""
    import signal
    import threading

    term = _Term()
    if threading.current_thread() is not threading.main_thread():
        yield term
        return

    def _raise(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if term.held:
            term.pending = signum
            return
        raise SystemExit(128 + signum)

    before = signal.signal(signal.SIGTERM, _raise)
    try:
        yield term
        term.release()
    except BaseException:
        if term.held and term.pending:
            raise SystemExit(128 + term.pending)
        raise
    finally:
        signal.signal(signal.SIGTERM, before)


def _stop_group(proc, grace_s: float) -> None:
    """Stop the eval's group, reaping its leader as it goes; an unreaped leader makes killpg say EPERM on macOS. #673, #677."""
    from harness import workqueue
    workqueue.stop_group(proc.pid, grace=grace_s, proc=proc)


def _screen_refusal(a, lane: str, spec: str) -> str:
    """Why a repo pairing waits for the challenger's repo screen, or ""; a held pause resumes. #1353."""
    from evals import repo_screen
    from harness import identity, paused
    from harness import memory_store as ms
    if lane != repo_screen.LANE or getattr(a, "unscreened", False):
        return ""
    store = ms.connect()
    try:
        if paused.find(store, lane, spec):
            return ""
        return repo_screen.refusal(store, [spec], identity.lane_cases(lane))
    finally:
        store.close()


def _slice(plan, elapsed: float):
    """(this launch's share of the plan, whether it is the budget's last): one look interval of what is left. #1353."""
    from harness import looks
    if plan.budget_s is None:
        return plan, True
    left = max(0.0, plan.budget_s - elapsed)
    step = float(looks.LOOK_INTERVAL_S or 0.0)
    deadline = None if plan.deadline_s is None else max(0.0, plan.deadline_s - elapsed)
    last = step <= 0 or step >= left
    return replace(plan, budget_s=left if last else step, deadline_s=deadline), last


def _between_looks(proc, out, last: bool, before: int) -> bool:
    """Whether a slice stopped at its own look time, with budget left and new rows, so the run goes on after a look."""
    if last or getattr(proc, "timed_out", False) or proc.returncode != watch.PAUSED:
        return False
    progress = watch.read_progress(out)
    if not str(progress.get("why") or "").startswith("paused at its stop time"):
        return False
    return len((watch.read(out) or ({}, []))[1]) > before


def _argv(lane: str, plan, out, inc_spec: str, spec: str, resume: bool = False,
          unscreened: bool = False) -> list[str]:
    """The paired evals.run: pause at this sweep's slice, a plan per case for a watchdog, resume when held. #813, #810."""
    from harness import runner_gaps
    argv = [*runner_gaps.launcher([inc_spec, spec], ["uv", "run", "python"], lane), "-m", "evals.run", "--modality", lane,
            "--repeat", str(plan.repeat), "--out", str(out),
            "--candidates", f"{inc_spec},{spec}"]
    if plan.side != "all":
        argv += ["--split", plan.side]
    if plan.budget_s is not None:
        argv += ["--stop-at", f"{time.time() + plan.budget_s:.0f}"]
    est = plan.estimate or {}
    each = [est.get(f"{who}_s") and est[f"{who}_s"] * (est.get(f"{who}_calls") or 1)
            for who in ("incumbent", "challenger")]
    if all(each):
        argv += [x for s_ in each for x in ("--plan-s", f"{s_:.2f}")]
    if (getattr(plan, "reuse", None) or {}).get("reused"):
        from harness import reuse
        argv += ["--reuse", str(Path(out) / reuse.REUSE_FILE)]
    if resume:
        argv.append("--resume")
    if unscreened:
        # The measure step judged the challenger's screen itself; the lane's incumbent needs none. #1353.
        argv.append("--unscreened")
    return argv


def _held(lane: str, inc_spec: str, spec: str, split, name: str, sweep):
    """(the pairing's live pause if it may resume, the identity a resume needs); a changed exam is reported stale. #813."""
    from harness import knobs, paused, watchdog
    from harness import memory_store as ms
    ident = paused.identity(lane, inc_spec, _settings(lane, inc_spec, spec), knobs.settings(lane),
                            split.version)
    store = ms.connect()
    try:
        held = paused.find(store, lane, spec)
        found = None if held else paused.abandoned(store, paths.home() / "runs", lane, inc_spec, spec)
        stopped = bool(held) and watchdog.overrun_stopped(store, held["out"])
    finally:
        store.close()
    if stopped:
        _ended(name, held, held["out"], sweep)
        return None, ident
    if found:
        # A run stopped with no pause recorded (the watchdog before #864) still has its rows. #864.
        print(f"  {name}: resuming {found['out']}, stopped at {found['done']} case(s) with no pause recorded",
              flush=True)
        return {**found, "identity": ident}, ident
    if not held:
        return None, ident
    changed = watch.differs(held["identity"], ident)
    if not changed and not (Path(held["out"]) / watch.CHECKPOINT).is_file():
        changed = ["its checkpoint"]
    if changed:
        _stale(held, f"{', '.join(changed)} changed", name, sweep)
        return None, ident
    return held, ident


def _stale(held: dict, what: str, name: str, sweep) -> None:
    why = (f"stale: {what} since the pause at {held['done']}/{held['total']}; restarted, "
           f"the paused rows stay in {held['out']}")
    if held.get("id") is not None:
        _settle_pause(held["id"], "stale", why)
    print(f"  {name}: {why}", flush=True)
    if sweep is not None:
        sweep.lines.append(f"{name}: {why}")


def _ended(name: str, held, out, sweep) -> int:
    """A run the watchdog stopped as an overrun: ended and flagged, its rows kept, never resumed. #1409."""
    why = f"stopped by the watchdog as an overrun: a suspected harness defect, not resumed; its rows stay in {out}"
    if held and held.get("id") is not None:
        _settle_pause(held["id"], "defect", why)
    if sweep is not None:
        sweep.lines.append(f"{name}: {why}")
    return err(f"{name}: {why}")


def _settle_pause(pause_id: int, state: str, why: str) -> None:
    from harness import paused
    from harness import memory_store as ms
    store = ms.connect()
    try:
        paused.settle(store, pause_id, state, why)
    finally:
        store.close()


def _resumed_plan(stored: dict, fresh):
    """The stored plan's exam (repeat, side, power) with this sweep's budget and deadline."""
    from dataclasses import fields

    from harness import power
    names = {f.name for f in fields(power.Plan)}
    got = power.Plan(**{k: v for k, v in stored.items() if k in names})
    if got.odds is not None:
        got = replace(got, odds=tuple(got.odds))
    # The exam is kept; its price is this sweep's, or a stale screen price judges the run. #864.
    return replace(got, budget_s=fresh.budget_s, deadline_s=fresh.deadline_s, estimate=fresh.estimate)


def _recovered_plan(held: dict, fresh):
    """A run found by its checkpoint alone resumes the exam the checkpoint names, at this sweep's price. #864."""
    ident = held.get("checkpoint") or {}
    return replace(fresh, repeat=int(ident.get("repeat") or fresh.repeat), side=ident.get("split") or "all")


def _signalled(rc) -> bool:
    """Whether a run's exit says a signal stopped it, raw or as a shell's 128 + signal."""
    import signal
    stops = {getattr(signal, n, None) for n in ("SIGTERM", "SIGKILL", "SIGINT")} - {None}
    return rc is not None and (rc < 0 or rc - 128 in stops)


def _paused(name: str, lane: str, inc_spec: str, spec: str, split, plan, out, held, ident, sweep,
            interim: bool = False, spans: int = 1) -> int:
    """A run paused at its slice: take an interim look, then stop early on it or keep the pause for the next sweep. #813.

    `interim` is a look between slices of one launch (#1353): the pause is kept for a crash, the sweep is not told.
    """
    import math

    from harness import adopt, candidates, looks, paused, power
    from harness import memory_store as ms
    got = watch.read(out)
    rows = got[1] if got else []
    progress = watch.read_progress(out)
    keys = {spec_: key for key, spec_ in (progress.get("specs") or {}).items()}
    inc_key = keys.get(inc_spec) or candidates.key_of(inc_spec) or inc_spec
    ch_key = keys.get(spec) or candidates.key_of(spec) or spec
    taken = list((held or {}).get("looks") or [])
    store = ms.connect()
    try:
        tested = adopt.comparisons(store, lane, split.version)
        rows, _, taken_from = _merge_reused(store, out, plan, rows, {}, inc_key)
        screened = adopt.screened_cases(store, lane, (ch_key, spec))
    finally:
        store.close()
    look, verdict = looks.look(rows, lane=lane, inc_key=inc_key, ch_key=ch_key, split=split,
                               plan=plan.as_dict(), alpha=adopt.alpha_for(tested),
                               spent_before=taken[-1]["spent"] if taken else 0.0, n=len(taken) + 1,
                               spec=spec, tested=tested)
    if verdict is not None:
        verdict = _confirmed(verdict, rows, split, screened, _served(lane), inc_spec, spec, plan)
    taken.append(look.as_dict())
    print(f"    {look.text}", flush=True)
    done = len(rows) - (taken_from or {}).get("reused", 0)
    total = int(progress.get("total") or (plan.cases_run or 0) * plan.repeat * 2 or done)
    if verdict is not None:
        verdict = replace(verdict, evidence={**verdict.evidence, "split": split.as_dict(),
                                             "power": plan.as_dict(), "looks": taken,
                                             **({"reuse": taken_from} if taken_from else {})})
        print(f"    {'ADOPTED' if verdict.adopt else 'kept the incumbent'}: {verdict.why}", flush=True)
        _record(verdict, spec, progress.get("run_id"), out)
        if held:
            _settle_pause(held["id"], "done", look.text)
        if sweep is not None:
            sweep.lines.append(f"{name}: {look.text}")
        return 0
    per = plan.budget_s or 0.0
    rest = None if not plan.projected_s or not per else max(
        1, math.ceil(plan.projected_s * (1 - done / max(total, 1)) / per))
    why = (f"paused at {done}/{total} case(s); {look.text}"
           f"{f'; about {rest} more sweep(s) at {power._hm(per)} each' if rest else ''}")
    store = ms.connect()
    try:
        paused.save(store, lane=lane, inc_spec=inc_spec, spec=spec, proposal=name, out=str(out),
                    ident=ident, plan=plan.as_dict(), done=done, total=total, looks=taken,
                    run_id=progress.get("run_id"), machine_id=ms.remember_machine(store),
                    pause_id=held["id"] if held else None, why=why, spans=spans)
    finally:
        store.close()
    if interim:
        return 0
    print(f"  {name}: {why}", flush=True)
    if sweep is not None:
        sweep.lines.append(f"{name}: {why}")
        if str(progress.get("why") or "").startswith("paused on request"):
            # A memory pause frees this run's model for smaller ones; any other request stops the sweep. #1082.
            if watch.pause_reason(out) in MEMORY_PAUSES:
                sweep.squeezed = why
            else:
                sweep.halted = why
    # Paused, as a paused --confirm exits, so the queue records it paused, not done. #1374.
    return watch.PAUSED


def _stopped_at(out, key: str) -> int | None:
    """The yield stop point a finished run's receipt names for `key`; None when it names none. #1127."""
    try:
        receipt = json.loads((Path(out) / "results.json").read_text(encoding="utf-8")).get("receipt") or {}
    except (OSError, ValueError):
        return None
    return ((receipt.get("yield_stop") or {}).get(key) or {}).get("tokens")


def _merge_reused(store, out, plan, rows: list, summary: dict, inc_key: str):
    """(rows with the stored incumbent cells the run skipped, the summary over them, the reuse evidence). #1094."""
    from harness import reuse, yield_stop
    got = watch.read(out)
    applied = reuse.narrowed((got[0] if got else {}).get("reuse"), getattr(plan, "reuse", None))
    if not applied:
        return rows, summary, {}
    extra, gone = reuse.rows(store, applied, inc_key)
    # Stored draws are graded as this run graded its own: stopped at the incumbent's yield stop point. #1127.
    extra = yield_stop.rescore(extra, _stopped_at(out, inc_key))["rows"]
    rows = [*rows, *extra]
    summary = {**summary, inc_key: reuse.summary(rows, inc_key)} if summary else summary
    evidence = reuse.evidence(applied, gone)
    print(f"    {reuse.line({**applied, 'reused': len(extra)})}"
          f"{f'; {len(gone)} stored row(s) gone, unpaired' if gone else ''}", flush=True)
    return rows, summary, evidence


def _served(lane: str) -> str:
    from harness import adopt, winners
    return adopt.default_for(lane, winners.typed().get(lane, ""))


def _confirmed(verdict, rows, split, screened, served: str, inc_spec: str, spec: str, plan):
    """The gate's verdict after its confirmation cells, carrying what a night confirmation run needs. #725."""
    from harness import adopt
    got = adopt.confirm(verdict, rows, split, screened)
    if got.failure_class != reasons.CONFIRMING:
        return got
    held = {**got.evidence["confirm"], "served": served, "incumbent": inc_spec, "challenger": spec,
            "repeat": int(getattr(plan, "repeat", 1) or 1)}
    return replace(got, evidence={**got.evidence, "confirm": held})


def confirm_job(vid: int) -> int:
    """`soh adopt --confirm VID`: the night dev run that confirms or refuses a held holdout win. #725."""
    from types import SimpleNamespace
    from harness import adopt, candidates, holdout, reuse, screen
    from harness import memory_store as ms
    store = ms.connect()
    try:
        row = store.execute("SELECT v.failure_class, v.power, v.detail, v.decided_at, p.name, p.state_verdict_id "
                            "FROM verdicts v "
                            "LEFT JOIN proposals p ON p.id = v.proposal_id WHERE v.id = ?", (vid,)).fetchone()
    finally:
        store.close()
    if row is None:
        return err(f"no verdict {vid}")
    if row["failure_class"] != reasons.CONFIRMING or row["state_verdict_id"] not in (None, vid):
        print(f"  verdict {vid} is not a held holdout win any more, so there is nothing to confirm", flush=True)
        return 0
    held = (json.loads(row["power"] or "{}") or {}).get("confirm") or {}
    lane = (row["detail"] or "").split(":", 1)[0].strip()
    inc_spec, spec, name = held.get("incumbent", ""), held.get("challenger", ""), row["name"] or held.get("challenger", "")
    was = held.get("served") or inc_spec
    now = _served(lane)
    if not inc_spec or not spec:
        return err(f"verdict {vid} does not name the pair it held, so it cannot be confirmed")
    if now != was and (screen.candidate_for(lane, now) or now) != was:
        print(f"  verdict {vid}: the {lane} lane no longer serves {was} ({now} now), so a confirmation against "
              f"it decides nothing; the adopt retest measures {spec} against {now}", flush=True)
        return 0
    split = holdout.for_lane(lane)
    repeat = int(held.get("repeat") or 1)
    side = "all" if split.too_small else "dev"
    out, data = _confirm_dir(lane, [inc_spec, spec], repeat, side, since=float(row["decided_at"] or 0))
    if data:
        print(f"    {out} finished without a verdict; recording it from its receipt (verdict {vid})", flush=True)
    else:
        proc, ran = _confirm_run(lane, inc_spec, spec, name, repeat, split, out, vid)
        if out is not None and proc.returncode == watch.STALE:
            print(f"    {out} ran another exam, so the confirmation is starting fresh", flush=True)
            proc, ran = _confirm_run(lane, inc_spec, spec, name, repeat, split, None, vid)
        out = ran
        if proc.returncode == watch.PAUSED:
            return _confirm_paused(vid, lane, inc_spec, spec, out)
        if proc.returncode != 0:
            err(proc.stderr.strip()[-400:] or "no stderr")
            return 1
        data = _receipt_at(out)
        if not data:
            return err(f"verdict {vid}: the confirmation run stored no receipt at {out}")
    store = ms.connect()
    try:
        candidates.from_receipt(store, data.get("specs") or {}, lane=lane, proposals={spec: name})
        inc_key, ch_key = candidates.key_for(store, inc_spec), candidates.key_for(store, spec)
        stored = SimpleNamespace(reuse=reuse.read(Path(out) / reuse.REUSE_FILE))
        rows = _merge_reused(store, out, stored, data.get("rows") or [], {}, inc_key)[0]
    finally:
        store.close()
    won = adopt.Verdict(lane, inc_key, ch_key, True, f"won the holdout (verdict {vid})")
    verdict = adopt.confirm(won, rows, split, frozenset(held.get("screened") or ()), fresh=True)
    if verdict.failure_class == reasons.CONFIRMING:
        return err(f"verdict {vid}: the confirmation run has no case outside the screened ones, so it decides nothing")
    print(f"    {'ADOPTED' if verdict.adopt else 'kept the incumbent'}: {verdict.why}", flush=True)
    _record(verdict, spec, data.get("run_id"), out)
    return 0


def _confirm_dir(lane: str, pair: list, repeat: int, side: str, since: float = 0.0) -> tuple:
    """(dir, None) for the newest unfinished confirmation of this pair and exam, to resume; (dir, receipt) for one
    finished since `since` that no verdict was read from, to record; (None, None) for neither. #1357."""
    from harness import holdout
    from harness import memory_store as ms
    for out in sorted((paths.home() / "runs").glob(f"*-confirm-{lane}"), reverse=True):
        had = watch.read(out)
        ident = had[0] if had else {}
        if not (had and list(ident.get("candidates") or ()) == list(pair) and int(ident.get("repeat") or 1) == repeat
                and (ident.get("split") or "all") == side):
            continue
        if watch.read_progress(out).get("state") != "done":
            return out, None
        if ident.get("split_version", holdout.version(lane)) != holdout.version(lane):
            continue
        if (out / watch.PROGRESS).stat().st_mtime < since:
            continue
        data = _receipt_at(out)
        if not data or data.get("run_id") is None:
            continue
        store = ms.connect()
        try:
            judged = store.execute("SELECT 1 FROM verdicts WHERE run_id = ?", (int(data["run_id"]),)).fetchone()
        finally:
            store.close()
        if judged is None:
            return out, data
    return None, None


def _confirm_run(lane, inc_spec, spec, name, repeat, split, out, vid):
    """(process, out dir) of the confirmation eval, resuming `out` when one is named. #1357."""
    from harness import runner_gaps, screen
    resume = out is not None
    out = out or paths.home() / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-confirm-{lane}"
    argv = [*runner_gaps.launcher([inc_spec, spec], ["uv", "run", "python"], lane), "-m", "evals.run", "--modality", lane,
            "--repeat", str(repeat), "--out", str(out), "--candidates", f"{inc_spec},{spec}"]
    if not split.too_small:
        argv += ["--split", "dev"]
    if resume:
        argv += ["--resume"]
    taken = _confirm_reuse(lane, inc_spec, spec, split, repeat, out, resume)
    if taken:
        argv += ["--reuse", str(taken)]
    route = screen.routed_gateway(name)
    if route:
        argv += ["--gateway", route]
    print(f"\n  {lane}: {'resuming' if resume else 'confirming'} {spec} over {inc_spec} on dev (verdict {vid})"
          f"\n    {' '.join(argv)}", flush=True)
    return _launch(argv), out


def _confirm_reuse(lane, inc_spec, spec, split, repeat, out, resume: bool):
    """The reuse file a confirmation passes: a resumed run keeps its own, a fresh one plans it. #1442, #1094."""
    from harness import reuse
    path = Path(out) / reuse.REUSE_FILE
    if resume:
        return path if path.is_file() else None
    got = _stored_cells(lane, inc_spec, spec, "all" if split.too_small else "dev", repeat)
    if reuse.line(got):
        print(f"    reuse: {reuse.line(got)}", flush=True)
    return reuse.write(out, inc_spec, got) if got.get("reused") else None


def _confirm_paused(vid: int, lane: str, inc_spec: str, spec: str, out) -> int:
    """A paused confirmation records no verdict and queues its own continuation for the next night. #1357."""
    from harness import adopt, workqueue
    from harness import memory_store as ms
    store = ms.connect()
    try:
        job = adopt.queue_confirmation(store, vid, adopt.Verdict(lane, inc_spec, spec, False, ""),
                                       start=workqueue.next_night(time.time()))
    finally:
        store.close()
    then = f"; it resumes as job {job['id']}" if job else ""
    print(f"    paused at {out}: {watch.pause_reason(out) or 'on request'}{then}", flush=True)
    return watch.PAUSED


def _record(verdict, spec: str, run_id, out) -> None:
    """Record the verdict with its planned and observed seconds per case beside it. #810, #813."""
    from harness import adopt
    from harness import memory_store as ms
    progress = watch.read_progress(out)
    planned, seen = _per_case(progress.get("planned_s_per_case")), _per_case(progress.get("observed_s_per_case"))
    store = ms.connect()
    try:
        # On the proposal the candidate maps to, so it leaves survivors. #393.
        vid = adopt.record(store, verdict, spec=spec, run_id=run_id)
        store.execute("UPDATE verdicts SET planned_s_per_case = ?, observed_s_per_case = ? WHERE id = ?",
                      (planned, seen, vid))
        store.commit()
        if verdict.failure_class == reasons.CONFIRMING:
            job = adopt.queue_confirmation(store, vid, verdict)
            if job:
                print(f"    confirmation queued for the night as job {job['id']}", flush=True)
    except ms.IllegalTransition as exc:
        print(f"  skipped {exc}", flush=True)
    finally:
        store.close()


def _record_unrun(verdict, spec: str) -> None:
    """Record a verdict the plan reached without a run. #1049."""
    from harness import adopt
    from harness import memory_store as ms
    store = ms.connect()
    try:
        adopt.record(store, verdict, spec=spec)
    except ms.IllegalTransition as exc:
        print(f"  skipped {exc}", flush=True)
    finally:
        store.close()


def _per_case(by_key) -> float | None:
    """Wall seconds per paired case: the candidates' seconds per case summed, None when one is unknown."""
    got = list((by_key or {}).values())
    return round(sum(got), 3) if got and all(x is not None for x in got) else None


def _zero_pass(lane: str, inc_spec: str) -> dict | None:
    from harness import baseline, runs
    with runs.store() as store:
        return baseline.zero_pass(store, lane, inc_spec)


def take_measured(lane: str, inc_spec: str, zero: dict, dry_run: bool = False):
    """Adopt the best measured local candidate over a zero-pass typed incumbent when it wins; the verdict if it was adopted. #1110."""
    from harness import adopt, baseline, runs
    from harness import memory_store as ms
    with runs.store() as store:
        got = baseline.take(store, lane, inc_spec, zero)
        if got is None:
            print(f"    {lane}: {inc_spec} passed 0 of {zero['cases']} stored cases and no local candidate "
                  f"has a row on every case of the current exam, so the lane keeps it until one does", flush=True)
            return None
        print(f"    {lane}: {'ADOPTED' if got.adopt and not dry_run else 'would adopt' if got.adopt else 'not taken'}"
              f" {got.challenger}: {got.why}", flush=True)
        if not got.adopt or dry_run:
            return None
        try:
            adopt.record(store, got, spec=got.challenger, run_id=got.evidence["runs"][-1])
        except (adopt.Held, ms.IllegalTransition, ValueError) as exc:
            print(f"    not recorded: {exc}", flush=True)
            return None
        return got


def take_incumbents(want: str = "") -> list:
    """Each typed lane that never passes takes its incumbent from measurement before the sweep measures it. #1110."""
    from harness import adopt, screen, winners
    typed = winners.typed()
    out = []
    for lane in ([lanes.canonical(want)] if want else sorted(typed)):
        if not typed.get(lane):
            continue
        served = adopt.default_for(lane, typed[lane])
        inc_spec = screen.candidate_for(lane, served) or served
        zero = _zero_pass(lane, inc_spec)
        got = take_measured(lane, inc_spec, zero) if zero else None
        if got is not None:
            out.append(got)
    return out


def _settle(name: str, outcome: str, detail: str) -> None:
    from harness import memory_store as ms
    store = ms.connect()
    try:
        ms.decide(store, name, outcome, tier=ms.MEASURE, detail=detail[:200],
                  reason=reasons.CANDIDATE)
    except (KeyError, ms.IllegalTransition):
        pass
    finally:
        store.close()


def _summary_row(summary: dict, key: str) -> dict | None:
    """The summary entry under the receipt key the candidates table holds. #407."""
    if not key or key not in summary:
        return None
    return {**(summary[key] or {}), "candidate": key}


#: `_all_refused` found no rows under the key it was given while the receipt
#: held rows under others. Reported rather than returned as "": the lookup is
#: the thing that failed, and saying "it ran fine" would be a guess.
NO_ROWS_FOR_CANDIDATE = "no rows under that name in the receipt"


def _all_refused(rows, candidate: str) -> str:
    """The failure class, when EVERY row for `candidate` never reached a model.

    Empty when any row actually reached a model, because then the candidate
    really was measured and a low score is its own.

    MATCHED ON THE RECEIPT KEY, which is what the rows carry. A bare repo id
    matches nothing for an engine lane, where the key is `mflux/<id>-q8`, and
    "matched nothing" used to return "" -- the same answer as "it ran" -- so a
    mis-keyed lookup silently disabled the guard instead of failing. A safety
    check whose lookup miss looks like a pass is worse than no check.
    """
    mine = [r for r in rows or [] if r.get("candidate") == candidate]
    if not mine:
        # No rows at all is a different fact and the caller handles it; no
        # rows for THIS candidate when others have some is a key mismatch.
        return "" if not rows else NO_ROWS_FOR_CANDIDATE
    seen = {r.get("failure_class") or "" for r in mine}
    return sorted(seen)[0] if seen <= set(reasons.NEVER_RAN) else ""


def _receipt_at(out, conn=None) -> dict | None:
    """The stored run for the directory this invocation named. #222, #410.

    The only way to know which run a receipt describes is to have named it.
    """
    from harness import runs
    with runs.store(conn) as c:
        return runs.receipt_at(c, out)
