"""The method registry: a named transform over a base candidate, `<name>:<args>:<base>`,
run over the base's own runner and route. #576."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

#: Where the loop's crossings are recorded: the sighting's source and the proposal's kind.
CROSSING_SOURCE = "method-crossing"
CROSSING_KIND = "method"

#: Text lanes whose cases are free text a second sample can change. decide samples
#: at temperature 0 and agent drives a tool loop, so neither is a best-of lane.
SAMPLED_TEXT_LANES = ("code", "web", "svg")
TEXT_LANES = ("code", "web", "svg", "extract")


@dataclass(frozen=True)
class Parsed:
    method: "Method"
    args: tuple
    base: str
    spec: str


@dataclass(frozen=True)
class Method:
    name: str
    grammar: str
    #: Lanes it applies to; the loop crosses it with these lanes' incumbents.
    lanes: tuple
    #: The Case.methods label it counts as; "" means whatever its base counts as.
    takes: str
    note: str
    #: (parsed, base_builder, outdir) -> runner. base_builder(spec) builds the base's runner.
    build: Callable
    #: Leading integer arguments before the base, with the defaults the loop crosses at.
    arity: int = 0
    defaults: tuple = ()
    minimum: int = 1
    #: The one modality its output is, or "" for its base's.
    modality: str = ""
    #: The lane whose incumbent is its base when the loop crosses it; "" is the lane itself.
    base_lane: str = ""
    #: Whether the loop crosses it with incumbents without anyone typing it.
    crosses: bool = True
    #: vector.TRACE_PRESETS key, for a trace method.
    preset: str = ""
    #: (parsed, lane, prompt, ask, slots) -> (text, cost): how a lane command serves it; None for trace.
    serve: Callable | None = None
    #: (parsed) -> model calls one attempt makes on its base; None is one. #673.
    per_attempt: Callable | None = None
    extra: dict = field(default_factory=dict)

    def compose(self, base: str, *args) -> str:
        got = [str(a) for a in (args or self.defaults)]
        return ":".join([self.name, *got, base])


def parse(spec: str) -> Parsed | None:
    """The method, its arguments and its base; None when `spec` is not a method. Raises
    ValueError for a method spec that does not parse."""
    spec = (spec or "").strip()
    head, sep, rest = spec.partition(":")
    head = head.partition(",")[0].strip()
    method = REGISTRY.get(head)
    if method is None:
        return None
    args = []
    for _ in range(method.arity):
        arg, sep2, rest = rest.partition(":")
        try:
            n = int(arg)
        except ValueError:
            raise ValueError(f"{spec!r}: {method.grammar} needs a whole number, "
                             f"got {arg!r}") from None
        if n < method.minimum:
            raise ValueError(f"{spec!r}: {method.grammar} needs at least {method.minimum}")
        if not sep2:
            rest = ""
        args.append(n)
    if not sep or not rest.strip():
        raise ValueError(f"{spec!r} names no base; spelled {method.grammar}")
    return Parsed(method, tuple(args), rest.strip(), spec)


def is_method(spec: str) -> bool:
    try:
        return parse(spec) is not None
    except ValueError:
        return True


def base_of(spec: str) -> str:
    """The base a method spec composes over, or "" for anything else."""
    try:
        got = parse(spec)
    except ValueError:
        return ""
    return got.base if got else ""


def calls(spec: str) -> int:
    """Model calls one attempt of `spec` makes on its base: 1 for a plain model or a bad spec. #673."""
    try:
        parsed = parse(spec)
    except ValueError:
        return 1
    if parsed is None or parsed.method.per_attempt is None:
        return 1
    return max(1, int(parsed.method.per_attempt(parsed)))


def expected_calls(spec: str, rates=(), slots: int = 1) -> float:
    """Calls' worth of wall time one attempt of `spec` takes, given its base's per-case pass rates:
    best-of stops after the wave that passes; with no rates, every call. #807."""
    n = calls(spec)
    rates = list(rates)
    if not rates or base_of(spec) == "" or parse(spec).method.serve is not _serve_best_of:
        return n
    total = 0.0
    for p in rates:
        miss = 1.0
        for size in _waves(n, slots):
            total += miss
            miss *= (1.0 - p) ** size
    return round(total / len(rates), 2)


def slots_of(spec: str) -> int:
    """Requests the server of `spec`'s base answers at once: its llama-server slots, 1 when unknown. #807."""
    from harness import context
    return max(1, int(context.served_slots(base_of(spec) or spec) or 1))


def _waves(n: int, slots: int) -> list[int]:
    """Sample counts per wave: the first alone, since most cases pass it, then up to `slots` at once."""
    out, left, slots = [1], n - 1, max(1, int(slots))
    while left > 0:
        out.append(min(slots, left))
        left -= out[-1]
    return out


#: _rank's key for a reply that passes every check with no warnings; best-of stops there. #807.
TOP = (True, 0)


def sample(n: int, slots, draw, rank, errors: tuple) -> tuple[list, list, int]:
    """([(index, key, result)], [errors raised], calls made): draw(i) up to n times in _waves,
    concurrently within a wave, stopping after the wave that ranks TOP. `slots` is an int or a
    callable asked only when a second wave is needed. #807."""
    from concurrent.futures import ThreadPoolExecutor

    def attempt(i):
        try:
            return True, draw(i)
        except errors as exc:
            return False, exc
    got, failed, made, sizes = [], [], 0, [1]
    for k in range(n):
        if made >= n:
            break
        if k == 1:
            sizes = _waves(n, slots() if callable(slots) else slots)
        wave = list(range(made, made + sizes[k]))
        if len(wave) == 1:
            outs = [attempt(wave[0])]
        else:
            with ThreadPoolExecutor(len(wave)) as pool:
                outs = list(pool.map(attempt, wave))
        made += len(wave)
        for i, (ok, val) in zip(wave, outs):
            if ok:
                got.append((i, rank(val), val))
            else:
                failed.append(val)
        if any(key == TOP for _, key, _ in got):
            break
    return got, failed, made


def build(spec: str, base_builder, outdir=None):
    """The runner for a method spec. SystemExit on a bad spec, as every runner is built."""
    try:
        parsed = parse(spec)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    runner = parsed.method.build(parsed, base_builder, outdir)
    return runner


def applicable(lane: str) -> list[Method]:
    return [m for m in REGISTRY.values() if lane in m.lanes]


def crossings(lane: str, incumbent_of) -> list[str]:
    """Each crossing method applicable to `lane`, composed over the incumbent it takes."""
    out = []
    for m in applicable(lane):
        if not m.crosses:
            continue
        base = incumbent_of(m.base_lane or lane)
        if not base or is_method(base):
            continue
        out.append(m.compose(base))
    return out


def weights_of(spec: str) -> str:
    """The repo id a method's base downloads, or "" when its runner finds its own."""
    base = base_of(spec)
    if not base:
        return ""
    model = base.partition(",")[0].strip()
    from harness import models
    # A gateway entry is named by its repo id now (#670); the gateway serves it, as it did its nickname.
    if models.on_gateway(model):
        return ""
    return model if "/" in model and ":" not in model else ""


#: The first call of plan: a plan, and no answer yet.
PLAN_PROMPT = """Before answering, write a short numbered plan for the task below.
Do not write the answer itself.

TASK:
{task}"""

#: The second call of plan: the task again, with the plan to follow.
ANSWER_PROMPT = """{task}

Follow this plan:
{plan}"""


def run(spec: str, lane: str, prompt: str, ask, slots: int | None = None) -> tuple[str, dict]:
    """(text, cost) for `prompt` served by `spec`, where ask(prompt, modality) -> text is one call
    on its base's route, safe to make from several threads. A plain model is one ask and {}.
    `slots` None asks the base's server. ValueError for a method no text call serves. #581, #807."""
    parsed = parse(spec)
    if parsed is None:
        return ask(prompt, lane), {}
    if parsed.method.serve is None:
        raise ValueError(f"{spec} draws with an image engine rather than answering in text; "
                         f"run `soh svg` for it")
    return parsed.method.serve(parsed, lane, prompt, ask, slots)


def text_method(spec: str) -> bool:
    """Whether `spec` is a method a text call serves (best-of, plan)."""
    try:
        parsed = parse(spec)
    except ValueError:
        return False
    return parsed is not None and parsed.method.serve is not None


def _rank(lane: str, text: str) -> tuple:
    """The lane command's own check of a reply as a key: passing first, then fewer warnings."""
    from harness import completion
    from harness.checks import code as code_check, html as html_check, svg as svg_check
    body = completion.artifact(text, lane)
    if lane == "code":
        broken = code_check.syntax_error(body) if body.strip() else "empty"
        missing = [] if broken else code_check.unresolvable_imports(body)
        return (not broken, -len(missing))
    checker = {"svg": svg_check.check, "web": html_check.check}.get(lane)
    if checker is None:
        return (bool(body.strip()), 0)
    got = checker(text)
    return (bool(got.ok), -len(got.warnings))


def _serve_plan(parsed: Parsed, lane: str, prompt: str, ask, slots=None) -> tuple[str, dict]:
    plan = ask(PLAN_PROMPT.format(task=prompt), "")
    answer = ask(ANSWER_PROMPT.format(task=prompt, plan=plan.strip()), lane)
    return answer, {"method": parsed.method.name, "base": parsed.base, "calls": 2}


def _serve_best_of(parsed: Parsed, lane: str, prompt: str, ask, slots=None) -> tuple[str, dict]:
    import time
    from harness import completion
    n = parsed.args[0]
    started = time.perf_counter()
    got, failed, made = sample(n, slots if slots is not None else (lambda: slots_of(parsed.base)),
                               lambda i: ask(prompt, lane), lambda text: _rank(lane, text),
                               (completion.CompletionError,))
    if not got:
        raise (failed[0] if failed else completion.CompletionError("no sample came back"))
    i, _, best = max(got, key=lambda g: (g[1], -g[0]))
    return best, {"method": parsed.method.name, "base": parsed.base, "calls": made,
                  "samples": n, "chosen": i + 1, "wall_s": round(time.perf_counter() - started, 2)}


def cost(incumbent: dict, challenger: dict, spec: str) -> dict:
    """What a method paid for its result beside the incumbent: calls and median latency; {} for
    anything that is not a method."""
    try:
        parsed = parse(spec)
    except ValueError:
        return {}
    if parsed is None:
        return {}
    mine = float(challenger.get("median_s") or 0.0)
    theirs = float(incumbent.get("median_s") or 0.0)
    return {"method": parsed.method.name, "base": parsed.base,
            "calls": float(((challenger.get("metrics") or {}).get("method_calls")) or 1.0),
            "median_s": mine, "incumbent_median_s": theirs,
            "latency_ratio": round(mine / theirs, 2) if theirs > 0 else None}


def cost_note(incumbent: dict, challenger: dict, spec: str) -> str:
    """The cost as a sentence for the verdict a person reads."""
    got = cost(incumbent, challenger, spec)
    if not got:
        return ""
    ratio = (f", {got['latency_ratio']:.1f}x the incumbent's median latency"
             if got["latency_ratio"] is not None else "")
    return (f"cost: {got['method']} made {got['calls']:.1f} calls a case{ratio} "
            f"({got['median_s']:.2f}s against {got['incumbent_median_s']:.2f}s)")


# ---- the methods -----------------------------------------------------------------

def _trace(parsed: Parsed, base_builder, outdir):
    from evals.runners.trace import TraceRunner
    from harness.engines import resolve
    name, spec = parsed.method.name, parsed.base
    try:
        engine = resolve(spec)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if outdir is None:
        raise SystemExit(f"{parsed.spec} writes images; pass --out")
    return TraceRunner(engine, outdir, preset=parsed.method.preset)


def _best_of(parsed: Parsed, base_builder, outdir):
    from evals.runners.method import BestOfRunner
    return BestOfRunner(base_builder(parsed.base), parsed.args[0], spec=parsed.base)


def _plan(parsed: Parsed, base_builder, outdir):
    from evals.runners.method import PlanRunner
    from evals.runners.text import CompletionRunner
    base = base_builder(parsed.base)
    if not isinstance(base, CompletionRunner):
        raise SystemExit(f"{parsed.spec}: plan needs a text base served through a text "
                         f"server, and {parsed.base} is not one")
    return PlanRunner(base)


REGISTRY: dict[str, Method] = {m.name: m for m in (
    Method("trace", "trace:<image engine>", ("svg",), "trace",
           "draw a raster with an image engine, then vectorize it", _trace,
           modality="svg", base_lane="image", preset="illustration"),
    Method("trace-icon", "trace-icon:<image engine>", ("svg",), "trace",
           "trace with the icon preset", _trace,
           modality="svg", base_lane="image", preset="icon", crosses=False),
    Method("best-of", "best-of:<n>:<base>", SAMPLED_TEXT_LANES, "",
           "sample n at the lane's temperature, keep what the lane's checks score highest",
           _best_of, arity=1, defaults=(3,), minimum=2, serve=_serve_best_of,
           per_attempt=lambda p: p.args[0]),
    Method("plan", "plan:<base>", TEXT_LANES, "",
           "ask for a plan, then answer with it: two calls", _plan,
           serve=_serve_plan, per_attempt=lambda p: 2),
)}


#: candidate prefix -> vector.TRACE_PRESETS key, read by evals.run.
TRACE_PRESETS = {m.name: m.preset for m in REGISTRY.values() if m.preset}
