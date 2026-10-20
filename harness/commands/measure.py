"""The measure tier, verify and throughput: run a candidate's cases and settle what they say."""
from __future__ import annotations

import contextlib
import math
import time
from dataclasses import dataclass, replace
from pathlib import Path

from evals import watch
from harness import lanes, paths, reasons
from harness.commands.common import emit, err, note
from harness.commands import jobs as jobs_cmd


def cmd_verify(a) -> int:
    """Establish that each lane works, by running its own default. #234."""
    import subprocess

    from harness import report, verify

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
        got = verify.verdict(data) if proc.returncode == 0 else "broken"
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
    from harness import exclusive, serving, throughput, vllm
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
    with exclusive.held("eval"), contextlib.ExitStack() as stack:
        if serve:
            port = int(where.base.rsplit(":", 1)[1])
            note(f"  starting {serve} on port {port}", flush=True)
            srv = stack.enter_context(vllm.served(
                vllm.argv(serve, where.model, port), port,
                log=paths.home() / "logs" / f"{serve}-{port}.log"))
            pid = srv.proc.pid
        got = throughput.sweep(
            where.model, texts, levels=levels, max_tokens=a.max_tokens,
            gateway=where.base, timeout=getattr(a, "timeout", 300.0),
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


def measurable(store, top: int, want: str = "") -> list[dict]:
    """Survivors in the scoped lane, filtered before the limit. #386."""
    from harness import memory_store as ms
    rows = ms.survivors(store, limit=1_000_000)
    if want:
        rows = [r for r in rows if lanes.serves(r.get("lane"), want)]
    return rows[:top]


def resume_first(store, fresh: list[dict], want: str = "") -> list[dict]:
    """Paused measurements before anything new, each once. #813."""
    from harness import paused
    held = [{"name": p["proposal"] or p["challenger"], "lane": p["lane"]} for p in paused.waiting(store)
            if not want or lanes.serves(p["lane"], want)]
    names = {r["name"] for r in held}
    return held + [r for r in fresh if r.get("name") not in names]


def _measure_and_adopt(a, row: dict, sweep=None) -> int:
    """_measure, then unload the challenger it loaded. #444."""
    from harness import router
    loaded: list[str] = []
    try:
        return _measure(a, row, loaded, sweep)
    finally:
        for spec in loaded:
            router.release_spec(spec, f"measured {row['name']}")


def _measure(a, row: dict, loaded: list, sweep=None) -> int:
    """One challenger against the lane's incumbent, then the verdict.

    PAIRED AND IN ONE RUN. Both candidates see the same cases, the same repeat
    count and the same machine, so the only axis that moved is the candidate.
    Two separate runs would be two receipts that comparable() would refuse, and
    rightly.
    """
    from harness import adopt, candidates, screen, winners
    from harness import memory_store as ms

    name = row["name"]
    # A text candidate is filed under `code` and can be measured in web, svg
    # and extract too. When the caller scoped the loop to one of those, that
    # is the lane to measure in: the incumbent, the cases and the metric all
    # belong to the lane being asked about, not the one the row was filed
    # under. #207.
    want = (getattr(a, "lane", "") or "").strip().lower()
    lane = (want if want and lanes.serves(row.get("lane"), want)
            else lanes.canonical(row.get("lane")))
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
    if spec == inc_spec:
        # An adopted winner is the incumbent; measuring it against itself
        # wrote `declined` for the lane's own default. #393.
        print(f"  {name}: already the {lane} lane's default ({spec})")
        _settle(name, "measured", f"{lane}: already the lane's default")
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
    for _ in range(2):
        # NAME THE DIRECTORY, DO NOT GUESS AT IT AFTERWARDS: a newest-receipt read
        # took a stranger's run (`legacy-...` sorts above timestamps). #222.
        out = (Path(held["out"]) if held else paths.home() / "runs"
               / f"{time.strftime('%Y%m%d-%H%M%S')}-adopt-{lane}")
        argv = _argv(lane, plan, out, inc_spec, spec, resume=bool(held))
        # ROUTE IT THE WAY THE SCREEN DOES: LiteLLM refuses a repo id it has no alias for. #223, #206.
        route = screen.routed_gateway(name)
        if route:
            argv += ["--gateway", route]
        print(f"\n  {lane}: {name} against {incumbent}")
        print(f"    {' '.join(argv)}", flush=True)
        loaded.append(spec)
        proc = _launch(argv, deadline_s=plan.deadline_s)
        if proc.returncode == watch.STALE and held:
            _stale(held, "the run's own checkpoint is another exam", name, sweep)
            held = None
            continue
        break
    if getattr(proc, "timed_out", False) or proc.returncode == watch.PAUSED:
        return _paused(name, lane, inc_spec, spec, split, plan, out, held, ident, sweep)
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
    if not int(inc_row.get("passed") or 0):
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
    store = ms.connect()
    try:
        tested = adopt.comparisons(store, lane, split.version) if split is not None else 0
    finally:
        store.close()
    spent = taken[-1]["spent"] if taken else 0.0
    verdict = adopt.decide(lane, inc_row, ch_row, rows, split=split, plan=plan, spec=spec,
                           tested=tested, alpha=adopt.alpha_for(tested) - spent if taken else None)
    if taken:
        verdict = replace(verdict, evidence={**verdict.evidence, "looks": taken})
    print(f"    {'ADOPTED' if verdict.adopt else 'kept the incumbent'}: "
          f"{verdict.why}")
    _record(verdict, spec, data.get("run_id"), out)
    return 0


def _plan(a, lane: str, inc_spec: str, spec: str = "", sweep=None):
    """The lane's split and the repeat the paired gate needs on its holdout; this sweep's slice of it. #479, #591, #673, #806, #813."""
    from dataclasses import replace

    from evals.run import STOCHASTIC_MODALITIES
    from harness import adopt, candidates, completion, holdout, power, runs
    from harness import memory_store as ms

    split = holdout.for_lane(lane)
    settings = (completion.budget(lane), ())
    inc_key = candidates.key_of(inc_spec) or inc_spec
    store = ms.connect()
    try:
        machines = runs.here(store)
        draws, inc_s = power.served_profile(store, lane, inc_spec, settings, machines)
        basis = ""
        if inc_s is None and settings[0]:
            inc_s, basis = power.served_bound(store, lane, inc_spec, settings, machines)
        median_s, calls, est = power.pair_cost(store, lane, incumbent=inc_key, incumbent_spec=inc_spec,
                                               incumbent_s=inc_s, challenger=spec,
                                               settings=settings, machines=machines,
                                               incumbent_basis=basis)
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
    if est["challenger_source"] not in ("measured", "like incumbent", "bounded") and est["challenger_s"] is not None:
        estimated = "; ".join(x for x in (estimated, f"challenger seconds per call "
                                          f"{est['challenger_s']:.0f}s by {est['challenger_source']}") if x)
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
    missing = power.unmeasured(draws, split.holdout)
    if missing and any(draws.values()):
        print(f"    projected: {len(missing)} of {len(split.holdout)} holdout "
              f"unmeasured, drawn from the incumbent's measured per-case rates",
              flush=True)
    return split, plan


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
    """SIGTERM the group, reap the leader, then SIGKILL what is left; an unreaped leader makes killpg say EPERM on macOS. #673."""
    import contextlib
    import os
    import signal
    import subprocess
    import sys

    from harness import workqueue
    if sys.platform == "win32":
        workqueue.stop_group(proc.pid, grace=grace_s)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=grace_s)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


def _argv(lane: str, plan, out, inc_spec: str, spec: str, resume: bool = False) -> list[str]:
    """The paired evals.run: pause at this sweep's slice, a plan per case for a watchdog, resume when held. #813, #810."""
    from harness import runner_gaps
    argv = [*runner_gaps.launcher([inc_spec, spec], ["uv", "run", "python"]), "-m", "evals.run", "--modality", lane,
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
    if resume:
        argv.append("--resume")
    return argv


def _held(lane: str, inc_spec: str, spec: str, split, name: str, sweep):
    """(the pairing's live pause if it may resume, the identity a resume needs); a changed exam is reported stale. #813."""
    from harness import completion, knobs, paused
    from harness import memory_store as ms
    ident = paused.identity(lane, inc_spec, (completion.budget(lane), ()), knobs.settings(lane),
                            split.version)
    store = ms.connect()
    try:
        held = paused.find(store, lane, spec)
        found = None if held else paused.abandoned(store, paths.home() / "runs", lane, inc_spec, spec)
    finally:
        store.close()
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


def _paused(name: str, lane: str, inc_spec: str, spec: str, split, plan, out, held, ident, sweep) -> int:
    """A run paused at its slice: take an interim look, then stop early on it or keep the pause for the next sweep. #813."""
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
    finally:
        store.close()
    look, verdict = looks.look(rows, lane=lane, inc_key=inc_key, ch_key=ch_key, split=split,
                               plan=plan.as_dict(), alpha=adopt.alpha_for(tested),
                               spent_before=taken[-1]["spent"] if taken else 0.0, n=len(taken) + 1,
                               spec=spec, tested=tested)
    taken.append(look.as_dict())
    print(f"    {look.text}", flush=True)
    done = len(rows)
    total = int(progress.get("total") or (plan.cases_run or 0) * plan.repeat * 2 or done)
    if verdict is not None:
        verdict = replace(verdict, evidence={**verdict.evidence, "split": split.as_dict(),
                                             "power": plan.as_dict(), "looks": taken})
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
                    pause_id=held["id"] if held else None, why=why)
    finally:
        store.close()
    print(f"  {name}: {why}", flush=True)
    if sweep is not None:
        sweep.lines.append(f"{name}: {why}")
        if str(progress.get("why") or "").startswith("paused on request"):
            sweep.halted = why
    return 0


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
