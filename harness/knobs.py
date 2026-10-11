"""Every outcome-gating constant is a hypothesis: its range, the lanes it shapes, and the limit that shows it binding (#636).

This is the registry `soh sensitivity` sweeps (#98). A knob with a `probe` is
swept offline against cached data; a knob with a `limit` is one an eval can hit,
and the limit is the predicate name a result row or a verdict records when it
does (`timeout_s>180`, `max_tokens.code>32768`, `ceiling_gb:>66`).

`inventory()` finds the numeric values whose names say they gate something:
constants, table entries, argument and field defaults, call literals and environment defaults, whatever their name. Every one is either registered here, named in NOT_GATING with a
reason, or in the shrinking backlog the tier-1 test holds.
"""
from __future__ import annotations

import ast
import importlib
import inspect as _inspect
import re
from dataclasses import dataclass
from pathlib import Path

from harness import completion

GIB = 1024 ** 3
REPO = Path(__file__).resolve().parent.parent

#: Name words that mark a constant as one that gates an outcome.
GATING_WORDS = frozenset({"MAX", "MIN", "TIMEOUT", "CAP", "LIMIT", "FLOOR", "CEILING", "BUDGET",
                          "THRESHOLD", "TOLERANCE", "TEMPERATURE", "TOKENS", "RESERVE", "ALPHA",
                          "CUTOFF", "MARGIN", "STEPS", "FRACTION", "WER", "CER", "INK", "MOTION",
                          "STDDEV", "F1", "DAYS", "SHARED", "POPULATION", "VOTES", "RETRIES",
                          "ATTEMPTS", "GRACE", "WAIT", "DELAY", "POLL", "INTERVAL", "STALL", "SECONDS",
                          "EFFECT", "CTX", "Z", "IDLE", "SLEEP"})
#: Name endings and phrases that mark a gate: seconds, a rate, a per-token or per-GiB allowance.
GATING_SUFFIXES = ("_S",)
GATING_PHRASES = ("PER_TOKEN", "PER_GIB")
#: Argument names whose numeric default or call-site literal gates an outcome.
GATING_PARAMS = frozenset({"timeout", "grace", "poll", "settle_s", "max_tokens", "max_new_tokens",
                           "limit", "levels"})
_UPPER = re.compile(r"_?[A-Z][A-Z0-9_]*")
_SITE = re.compile(r"(?P<rel>[\w/]+\.py):(?P<name>[\w.]+)(?P<keys>(?:\[\w+\])*)(?:\((?P<param>\w+)\))?")
_SHELL_DEFAULT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):?[-=](-?[0-9]+(?:\.[0-9]+)?)\}")

#: The until-predicate family a knob's limit is written in: `limit:name>N` or a machine fact `name:>N`.
LIMIT, MACHINE = "limit", "machine"

#: The lanes an eval asks for a text reply, the ones a reply budget is set for.
TEXT_LANES = tuple(completion.BUDGET)
#: The lanes whose replies go through the text runner's request and load timeouts; agent steps have their own.
REQUEST_LANES = tuple(lane for lane in TEXT_LANES if lane != "agent")


@dataclass(frozen=True)
class Knob:
    name: str
    #: "rel:NAME" or "rel:func(param)"; the first is the value swept, a second is the fallback a table falls back to.
    sites: tuple[str, ...]
    values: tuple
    lanes: tuple[str, ...] = ()
    #: The predicate name that shows this knob binding; "{lane}" is replaced per lane.
    limit: str = ""
    predicate: str = LIMIT
    #: The recorded limit is the value divided by this.
    scale: float = 1.0
    probe: str = ""
    #: Where an eval's receipt records it: "max_tokens" (its own field), "knobs" (Receipt.knobs), or "" (not the exam).
    receipt: str = ""
    #: The runner attribute a run sets for an override; "" rebinds the first site for the run instead.
    runner_attr: str = ""
    note: str = ""
    #: lane -> the range swept there, where a lane's default sits outside `values`. #654.
    lane_values: tuple = ()

    def default(self, lane: str = ""):
        got = resolve(self.sites[0])
        if isinstance(got, dict):
            if lane in got:
                return got[lane]
            return resolve(self.sites[1]) if len(self.sites) > 1 else None
        return got

    def values_for(self, lane: str = "") -> tuple:
        return dict(self.lane_values).get(lane, self.values)

    def limit_name(self, lane: str = "") -> str:
        if "{lane}" not in self.limit:
            return self.limit
        return self.limit.format(lane=lane) if lane else self.limit.split(".{lane}")[0]

    def limit_value(self, lane: str = ""):
        got = self.default(lane)
        return got / self.scale if self.scale != 1.0 else got


def _k(name, sites, values, lane_values=None, **kw) -> tuple[str, Knob]:
    per = tuple((lane, tuple(v)) for lane, v in sorted((lane_values or {}).items()))
    return name, Knob(name, tuple(sites), tuple(values), lane_values=per, **kw)


KNOBS: dict[str, Knob] = dict([
    _k("reply_budget", ["harness/completion.py:BUDGET", "harness/completion.py:MAX_TOKENS"],
       [2000, 4000, 8000, 16384, 32768, 65536], lanes=TEXT_LANES,
       lane_values={"claims": (200, 400, 800, 1600)}, limit="max_tokens.{lane}",
       receipt="max_tokens", note="the reply budget an eval asks every text reply at (#628)"),
    _k("request_timeout", ["harness/completion.py:TIMEOUT_S", "harness/completion.py:MIN_DECODE_TOK_S"],
       [60.0, 120.0, 180.0, 300.0, 600.0], lanes=REQUEST_LANES, limit="timeout_s", receipt="knobs", runner_attr="timeout",
       note="seconds one request may take; a big budget stretches it at the slowest decode"),
    _k("load_timeout", ["harness/completion.py:LOAD_TIMEOUT_S"],
       [600.0, 1200.0, 1800.0, 3600.0], lanes=REQUEST_LANES, limit="load_timeout_s", receipt="knobs", runner_attr="load_timeout",
       note="seconds the untimed first request may spend loading weights"),
    _k("memory_ceiling", ["harness/inspect.py:MEMORY_CEILING", "harness/inspect.py:MEMORY_CEILING_RAM_GB"],
       [8 * GIB, 16 * GIB, 22 * GIB, 32 * GIB, 96 * GIB], limit="ceiling_gb", predicate=MACHINE,
       scale=GIB, probe="memory_ceiling",
       note="the largest weight this machine can hold; measured on 32 GB and scaled by RAM (#96)"),
    _k("runaway_rate", ["harness/audio.py:SECONDS_PER_WORD_CEILING", "harness/audio.py:RUNAWAY_MIN_WORDS"],
       [0.6, 0.8, 0.95, 1.2, 2.0], lanes=("tts",), limit="seconds_per_word", receipt="knobs",
       note="seconds of speech per word above which tts ran away (#91)"),
    _k("audio_timeout", ["harness/audio.py:TIMEOUT_S"], [60.0, 120.0, 300.0, 600.0],
       lanes=("tts", "stt"), limit="audio_timeout_s", receipt="knobs", note="seconds one tts or stt request may take (#693)"),
    _k("download_cap", ["harness/fetching.py:MAX_DOWNLOAD"],
       [20 * GIB, 40 * GIB, 60 * GIB, 120 * GIB], limit="download_gib", scale=GIB,
       note="the largest download one fetch may take"),
    _k("min_shared", ["harness/neighbors.py:MIN_SHARED"], [1, 2, 3, 5, 8], probe="min_shared",
       note="how many of the crowd must star a repo for it to rank"),
    _k("population", ["harness/neighbors.py:POPULATION"], [1e5, 1e6, 5e6, 2e7, 1e8], probe="population",
       note="the world's star count, the denominator of enrichment"),
    _k("half_life", ["harness/neighbors.py:HALF_LIFE_DAYS"], [90.0, 365.0, 1095.0, 1e9], probe="half_life",
       note="push-date decay; 1e9 is the decay switched off"),
    _k("min_degree", ["harness/neighbors.py:cohort(min_degree)"], [1, 2, 3, 5], probe="min_degree",
       note="how many of the crowd must follow someone for a second hop to reach them"),
    _k("per_repo", ["harness/neighbors.py:cohort(per_repo)"], [4, 8, 12, 24], probe="per_repo",
       note="contributors taken from each seed repo"),
    _k("hops", ["harness/neighbors.py:cohort(hops)"], [1, 2, 3], probe="hops",
       note="how far from the seeds the crowd reaches"),
    _k("crowd_limit", ["harness/neighbors.py:cohort(limit)"], [100, 250, 450], probe="crowd_limit",
       note="crowd size; read n= rather than the value, offline only cached people answer"),
    _k("size_limit", ["harness/inspect.py:SIZE_LIMIT"], [2, 4, 12, 24, 64], probe="size_limit",
       note="how many named weights get sized per repo"),
    _k("dead_days", ["harness/inspect.py:UPSTREAM_DEAD_DAYS"], [180, 365, 730, 1095, 3650], probe="dead_days",
       note="when a repo counts as abandoned"),
    _k("clone_kb_cap", ["harness/inspect.py:CLONE_KB_CAP"], [10_000, 50_000, 250_000, 1_000_000],
       probe="clone_kb_cap", note="source tree size above which a repo is weights in git"),
    _k("binding_window", ["harness/binding.py:BINDING_WINDOW_DAYS"], [7, 14, 30, 90],
       note="days of runs and verdicts a binding count reads"),
    _k("binding_fraction", ["harness/binding.py:BINDING_FRACTION"], [0.02, 0.05, 0.1, 0.25],
       note="share of a lane's rows hitting a limit at which its knob is reported binding"),
    _k("claims_match_threshold", ["harness/checks/claims.py:MATCH_THRESHOLD"], [0.3, 0.4, 0.5, 0.6, 0.7],
       lanes=("claims",), limit="claims_match_threshold", receipt="knobs", note="word overlap at which an emitted claim is a reviewed one (#654)"),
    _k("claims_min_recall", ["harness/checks/claims.py:MIN_RECALL"], [0.25, 0.5, 0.75, 1.0],
       lanes=("claims",), limit="claims_min_recall", receipt="knobs", note="share of a case's good claims a reply must recover (#654)"),
    _k("code_check_timeout", ["harness/checks/code.py:DEFAULT_TIMEOUT"], [5.0, 15.0, 30.0, 60.0, 120.0],
       lanes=("code",), limit="code_check_timeout_s", receipt="knobs",
       note="wall clock a code answer and its checks may run; a case may set params.check_timeout (#693)"),
    _k("claude_code_timeout", ["evals/runners/claude_code.py:TIMEOUT_S"], [300.0, 600.0, 1200.0, 1800.0],
       lanes=REQUEST_LANES, limit="claude_code_timeout_s", receipt="knobs", note="seconds one claude -p reference answer may take (#693)"),
    _k("needle_serve_start", ["harness/needle.py:SERVE_START_S"], [30.0, 60.0, 120.0, 300.0],
       lanes=("decide", "agent"), limit="needle_serve_start_s", receipt="knobs", note="seconds needle --serve may take to report its address (#693)"),
    _k("chrome_render_timeout", ["harness/checks/render.py:CHROME_TIMEOUT_S"], [30.0, 60.0, 120.0, 300.0],
       lanes=("web",), limit="chrome_render_timeout_s", receipt="knobs", note="seconds headless Chrome may take to screenshot a page (#693)"),
    _k("svg_render_timeout", ["harness/checks/render.py:SVG_TIMEOUT_S"], [10.0, 30.0, 60.0, 120.0],
       lanes=("svg",), limit="svg_render_timeout_s", receipt="knobs", note="seconds rsvg-convert may take to draw one SVG (#693)"),
    _k("agent_steps_scale", ["evals/runners/agent.py:MAX_STEPS_SCALE"], [0.5, 1.0, 1.5, 2.0], lanes=("agent",),
       limit="agent_steps_scale", receipt="knobs", note="multiplies every agent case's own max_steps (#695)"),
    _k("agent_case_timeout", ["evals/runners/agent.py:CASE_TIMEOUT_S"], [600.0, 900.0, 1800.0, 3600.0],
       lanes=("agent",), limit="agent_case_timeout_s", receipt="knobs",
       note="seconds of an agent case's decoding and tools; prefill is not counted (#695)"),
    _k("agent_step_timeout", ["evals/runners/agent.py:STEP_TIMEOUT_S"], [180.0, 300.0, 600.0, 1200.0],
       lanes=("agent",), limit="agent_step_timeout_s", receipt="knobs", runner_attr="step_timeout",
       note="seconds one agent step may take, stretched for the reply budget (#695)"),
    _k("agent_pad_chars_per_token", ["evals/agent_pad.py:CHARS_PER_TOKEN"], [3, 3.5, 4],
       note="agent padding size estimate, used only where the served tokenizer cannot be asked (#695)"),
    _k("eval7b_slots", ["harness/context.py:EVAL_7B_SLOTS"], [1, 4, 8, 16, 32],
       note="llama-server slots Qwen2.5-7B-Instruct-Q4_K_M batches across; sets claims throughput, not a grade (#665)"),
    _k("eval7b_slot_ctx", ["harness/context.py:EVAL_7B_SLOT_CTX"], [3072, 4096, 8192],
       note="context each Qwen2.5-7B-Instruct-Q4_K_M slot is sized for; never under context.MIN_SLOT_CTX (#665)"),
    _k("ornith_slots", ["harness/context.py:ORNITH_SLOTS"], [1, 2, 4, 8],
       note="llama-server slots Ornith-1.5-35B-Q4_K_M batches across; sets code and agent lane throughput, not a grade (#682)"),
    _k("ornith_slot_ctx", ["harness/context.py:ORNITH_SLOT_CTX"], [131072, 262144],
       note="context each Ornith-1.5-35B-Q4_K_M slot is sized for; never under context.MIN_LONG_SLOT_CTX (#682)"),
    _k("binding_min_hits", ["harness/binding.py:BINDING_MIN_HITS"], [1, 3, 5, 10],
       note="fewer hits than this is never binding"),
    _k("adopt_effect", ["harness/power.py:EFFECT", "harness/power.py:DEFAULT_EFFECT"], [0.05, 0.1, 0.2, 0.3],
       note="smallest per-cell gain a lane adopts for; a null that could not see it is not a loss (#698)"),
    _k("adopt_alpha", ["harness/adopt.py:ALPHA"], [0.01, 0.025, 0.05, 0.1],
       note="level of the first paired test on a holdout; later ones face it over their comparison count (#698)"),
    _k("unseen_rate", ["harness/power.py:UNSEEN"], [0.25, 0.5, 0.75],
       note="pass rate a plan assumes for an incumbent with no draws; such a plan is unmeasured (#698)"),
])

#: The value a knob had on receipts written before it was recorded there, by knob name. #693.
UNRECORDED = {"code_check_timeout": 15.0, "audio_timeout": 120.0, "chrome_render_timeout": 60.0,
              "svg_render_timeout": 30.0, "claude_code_timeout": 600.0, "needle_serve_start": 60.0,
              "agent_steps_scale": 1.0, "agent_case_timeout": 900.0, "agent_step_timeout": 300.0}

#: Constants the inventory finds whose name says gate and whose value does not, each with why.
NOT_GATING: dict[str, str] = {
    "harness/mcp_server.py:MAX_INLINE_BYTES": "how a result is returned, inline or as a path; never what it is",
    "harness/context.py:MIN_SLOT_CTX": "the floor the eval7b_slot_ctx range is held to; a preset under it is refused (#665)",
    "harness/context.py:MIN_LONG_SLOT_CTX": "the floor the ornith_slot_ctx range is held to; a preset under it is refused (#682)",
    "evals/private.py:MIN_FRAGMENT": "which private text the leak scan looks for; never a lane's outcome (#654)",
    "harness/audio_server.py:environ(AUDIO_PORT)": "where the audio server listens; never what it answers (#706)",
    **{f"harness/nodes.py:{n}": "a node's default, set per node in nodes.yaml; it decides which machine "
       "answers, which the receipt records, never whether a request is answered (#684)"
       for n in ("CONNECT_TIMEOUT_S", "TIMEOUT_S", "COOLDOWN_S", "_to_node->params.update(max_retries)")},
    "harness/nodes.py:keychain->subprocess.run(timeout)": "how long the Keychain may take to hand over a key (#684)",
    **{f"harness/context.py:CACHE_BYTES[{t}]": "bytes per KV element of a cache type, a fact of the format (#706)"
       for t in ("f32", "f16", "bf16", "q8_0", "q5_1", "q5_0", "q4_1", "q4_0", "iq4_nl")},
    **{f"harness/usage.py:_UNITS[{u}]": "seconds in a day, hour, minute or second (#706)" for u in "dhms"},
    "harness/checks/image.py:ImageResult.stddev": "a measured result's value before it is measured (#706)",
    "harness/checks/video.py:VideoResult.motion": "a measured result's value before it is measured (#706)",
    "harness/checks/video.py:VideoResult.stddev": "a measured result's value before it is measured (#706)",
    "harness/checks/ocr.py:OcrResult.cer": "a measured result's value before it is measured (#706)",
    "evals/core.py:Receipt.max_tokens": "what a receipt records a run asked for; the budget itself is reply_budget (#706)",
    "harness/mcp_server.py:JobInfo.seconds": "how long a job took, as reported (#706)",
    **{site: "where a server listens; never what it answers (#706)" for site in (
        "scripts/serve-audio-cuda.sh:AUDIO_PORT",
        "scripts/serve-ds4.sh:DS4_PORT",
        "scripts/serve-eval.sh:LLAMACPP_PORT",
        "scripts/serve-gateway.sh:GATEWAY_PORT",
        "scripts/serve-llamacpp.sh:LLAMACPP_PORT",
        "scripts/serve-llamacpp.sh:LLAMACPP_PORT#2",
        "scripts/serve-llamacpp.sh:LLAMACPP_PORT#3",
        "scripts/serve-mcp.sh:MCP_PORT",
        "scripts/serve-mlx.sh:MLX_PORT",
        "scripts/serve-tts.sh:TTS_PORT",
        "scripts/services.sh:GATEWAY_PORT",
        "scripts/services.sh:LLAMACPP_PORT",
        "scripts/services.sh:LLAMACPP_PORT#2",
        "scripts/services.sh:LLAMACPP_PORT#3",
        "scripts/services.sh:AUDIO_PORT",
        "scripts/services.sh:DS4_PORT",
        "scripts/slots-sweep.sh:SWEEP_PORT",
        "scripts/smoke.sh:GATEWAY_PORT",
        "scripts/smoke.sh:MLX_PORT",
        "scripts/smoke.sh:TTS_PORT",
    )},
    "scripts/env.sh:HF_HUB_OFFLINE": "a switch, offline or not; never a threshold (#706)",
    "scripts/h3-weights-status.sh:BYTES": "the fallback of a measured size when none was measured (#706)",
    "scripts/router-max-models.sh:bytes": "the fallback of a measured RAM size when none was measured (#706)",
    "evals/runners/base.py:BaseRunner.failed(seconds)": "how long a failed case took, as reported (#706)",
    "evals/runners/agent.py:AgentRunner.failed(seconds)": "how long a failed case took, as reported (#706)",
    "harness/checks/ocr.py:check->OcrResult(cer)": "a measured result's value, as reported (#706)",
}


def _static(site: str):
    """The value of a site that only source holds: a call literal, an environment, shell or gateway default."""
    rel = site.split(":", 1)[0]
    text = (REPO / rel).read_text(encoding="utf-8")
    if rel.endswith(".py"):
        found = _sites(text, rel)
    elif rel.endswith(".sh"):
        found = _shell_sites(text, rel)
    else:
        found = _gateway_sites(text, rel)
    if site not in found:
        raise ValueError(f"not a site: {site!r}")
    return found[site]


def resolve(site: str):
    """The value a site names now: a module constant, a table entry, an argument or field default, or a literal in source."""
    m = _SITE.fullmatch(site)
    if m is None or m["name"] == "environ":
        return _static(site)
    got = importlib.import_module(m["rel"][:-3].replace("/", "."))
    try:
        for part in m["name"].split("."):
            got = getattr(got, part)
    except AttributeError:
        return _static(site)
    for key in re.findall(r"\[(\w+)\]", m["keys"] or ""):
        got = got[key]
    if m["param"]:
        return _inspect.signature(got).parameters[m["param"]].default
    return got


def _numeric(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp):
        return _numeric(node.operand)
    if isinstance(node, ast.BinOp):
        return _num_or_ref(node.left) and _num_or_ref(node.right) and (_numeric(node.left) or _numeric(node.right))
    if isinstance(node, ast.Dict):
        return bool(node.values) and all(_num_or_ref(v) for v in node.values) and any(_numeric(v) for v in node.values)
    return False


def _num_or_ref(node) -> bool:
    return _numeric(node) or isinstance(node, (ast.Name, ast.Attribute))


def named_gating(name: str) -> bool:
    """Whether a constant, table key or environment variable name says it gates an outcome."""
    name = name.upper().strip("_")
    return bool(GATING_WORDS & set(name.split("_")) or name.endswith(GATING_SUFFIXES)
                or any(p in name for p in GATING_PHRASES))


def _param_gating(name: str) -> bool:
    return name in GATING_PARAMS or name.endswith("_s") or named_gating(name)


def _literal(node) -> bool:
    if isinstance(node, (ast.Tuple, ast.List)):
        return bool(node.elts) and all(_literal(e) for e in node.elts)
    if isinstance(node, ast.UnaryOp):
        return _literal(node.operand)
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def _dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else ""
    return ""


def _table(rel: str, path: str, node) -> list[tuple[str, object]]:
    out = []
    for key, value in zip(node.keys, node.values):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and re.fullmatch(r"\w+", key.value)):
            continue
        here = f"{path}[{key.value}]"
        if isinstance(value, ast.Dict):
            out += _table(rel, here, value)
        elif _literal(value):
            out.append((f"{rel}:{here}", value))
    return out


def _env_default(node) -> tuple[str, object] | None:
    """(VAR, default node) for os.environ.get(VAR, N), os.getenv(VAR, N), or either `or N`."""
    def env(call):
        while isinstance(call, ast.Call) and not _dotted(call.func).endswith(("environ.get", "getenv")):
            if len(call.args) != 1:
                return None
            call = call.args[0]
        if (isinstance(call, ast.Call) and call.args and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)):
            return call
        return None
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == 2:
        call = env(node.values[0])
        return (call.args[0].value, node.values[1]) if call is not None else None
    if isinstance(node, ast.Call) and _dotted(node.func).endswith(("environ.get", "getenv")):
        call = env(node)
        if call is not None and len(call.args) == 2:
            return call.args[0].value, call.args[1]
    return None


def _number(node) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            float(node.value)
        except ValueError:
            return False
        return True
    return _literal(node)


def _value(node):
    got = ast.literal_eval(node)
    return float(got) if isinstance(got, str) else got


#: Methods whose first positional argument is a timeout: Popen/Event.wait, Thread/Process.join.
_POSITIONAL_TIMEOUT = ("wait", "join")


def _field(node) -> tuple[str, object] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, node.value
    return None


def _scoped(rel: str, body, scope: str) -> list[tuple[str, object]]:
    out = []

    def visit(node, scope, in_class=False):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = f"{scope}.{node.name}" if scope else node.name
            a = node.args
            pos = a.posonlyargs + a.args
            pairs = list(zip(pos[len(pos) - len(a.defaults):], a.defaults)) + [
                (arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
            out.extend((f"{rel}:{qual}({arg.arg})", d) for arg, d in pairs if _param_gating(arg.arg) and _literal(d))
            for child in node.body:
                visit(child, qual)
            return
        if isinstance(node, ast.ClassDef):
            qual = f"{scope}.{node.name}" if scope else node.name
            for child in node.body:
                visit(child, qual, in_class=True)
            return
        field = _field(node) if in_class else None
        if field and _param_gating(field[0]) and _literal(field[1]):
            out.append((f"{rel}:{scope}.{field[0]}", field[1]))
        if isinstance(node, ast.Call):
            callee = _dotted(node.func) or "call"
            here = scope or "<module>"
            out.extend((f"{rel}:{here}->{callee}({kw.arg})", kw.value) for kw in node.keywords
                       if kw.arg and _param_gating(kw.arg) and _literal(kw.value))
            if (isinstance(node.func, ast.Attribute) and node.func.attr in _POSITIONAL_TIMEOUT and node.args
                    and _literal(node.args[0])):
                out.append((f"{rel}:{here}->{callee}(timeout)", node.args[0]))
        got = _env_default(node)
        if got and _number(got[1]):
            out.append((f"{rel}:environ({got[0]})", got[1]))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    for stmt in body:
        visit(stmt, scope)
    return out


def _numbered(pairs) -> dict:
    """Each site once; a repeat of a site in the same file is a new site, `site#2`, so adding one is seen."""
    out, seen = {}, {}
    for site, value in pairs:
        seen[site] = seen.get(site, 0) + 1
        out[site if seen[site] == 1 else f"{site}#{seen[site]}"] = value
    return out


def _sites(text: str, rel: str) -> dict:
    out = []
    for stmt in ast.parse(text).body:
        name, value = _field(stmt) or (None, None)
        if name and _UPPER.fullmatch(name) and named_gating(name) and _numeric(value):
            out.append((f"{rel}:{name}", value))
        elif name and isinstance(value, ast.Dict):
            out += _table(rel, name, value)
        out += _scoped(rel, [stmt], "")
    return {site: _value(node) if _number(node) else None for site, node in _numbered(out).items()}


def gating(text: str, rel: str) -> list[str]:
    """Sites rel:NAME, rel:NAME[key], rel:func(param), rel:Class.field, rel:scope->callee(param), rel:environ(VAR), in source order."""
    return list(_sites(text, rel))


def _shell_sites(text: str, rel: str) -> dict:
    return _numbered((f"{rel}:{m[1]}", float(m[2]) if "." in m[2] else int(m[2]))
                     for m in _SHELL_DEFAULT.finditer(text))


def shell_defaults(text: str, rel: str) -> list[str]:
    """Sites rel:VAR of every numeric `${VAR:-N}` default in a shell script, whatever its name."""
    return list(_shell_sites(text, rel))


def _gateway_sites(text: str, rel: str) -> dict:
    import yaml
    data = yaml.safe_load(text)
    settings = data.get("litellm_settings") if isinstance(data, dict) else None
    out = {}

    def walk(d, prefix):
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v, f"{prefix}.{k}")
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{rel}:{prefix}.{k}"] = v
    if isinstance(settings, dict):
        walk(settings, "litellm_settings")
    return out


def gateway_settings(text: str, rel: str) -> list[str]:
    """Sites rel:litellm_settings.path of every number the gateway's LiteLLM settings set."""
    return list(_gateway_sites(text, rel))


def _production(rel: str) -> bool:
    return rel.endswith(".py") and rel.startswith(("harness/", "evals/")) and not rel.startswith("evals/cases/")


def inventory(root) -> list[str]:
    """Every gating value in production Python, top-level scripts and gateway config under `root`, by site."""
    from harness import repo
    root = Path(root)
    out = []
    for path in repo.publishable(root):
        rel = path.relative_to(root).as_posix()
        if not path.is_file():
            continue
        if _production(rel):
            out += gating(path.read_text(encoding="utf-8", errors="replace"), rel)
        elif re.fullmatch(r"scripts/[^/]+\.sh", rel):
            out += shell_defaults(path.read_text(encoding="utf-8", errors="replace"), rel)
        elif re.fullmatch(r"gateway/[^/]+\.ya?ml", rel):
            out += gateway_settings(path.read_text(encoding="utf-8", errors="replace"), rel)
    return out


def registered() -> set[str]:
    return {s for k in KNOBS.values() for s in k.sites}


def not_gating(site: str) -> bool:
    """Whether NOT_GATING names this exact site, or it is UNRECORDED's frozen legacy value of a registered knob."""
    m = re.fullmatch(r"harness/knobs\.py:UNRECORDED\[(\w+)\]", site)
    return site in NOT_GATING or bool(m and m[1] in UNRECORDED and m[1] in KNOBS)


def unregistered(found) -> list[str]:
    known = registered()
    return [s for s in found if s not in known and not not_gating(s)]


def census(root) -> dict:
    """How many gating constants the registry covers and how many it does not."""
    found = inventory(root)
    known = registered()
    return {"found": found, "registered": sum(1 for s in found if s in known),
            "not_gating": sum(1 for s in found if not_gating(s)),
            "unregistered": len(unregistered(found))}


def limits() -> dict:
    """The `limit:` values this harness currently chooses, by predicate name."""
    out = {}
    for k in KNOBS.values():
        if not k.limit or k.predicate != LIMIT:
            continue
        out[k.limit_name("")] = k.limit_value("")
        if "{lane}" in k.limit:
            for lane in k.lanes:
                out[k.limit_name(lane)] = k.limit_value(lane)
    return out


def settings(lane: str, overrides: dict | None = None) -> dict:
    """The exam knobs an eval of `lane` runs at, by knob name: their defaults, or the values a run names."""
    overrides = dict(overrides or {})
    unknown = sorted(n for n in overrides if n not in KNOBS or KNOBS[n].receipt != "knobs")
    if unknown:
        raise ValueError(f"not a knob a run can set: {', '.join(unknown)}")
    return {k.name: overrides.get(k.name, k.default(lane)) for k in KNOBS.values()
            if k.receipt == "knobs" and lane in k.lanes}


def rebind(overrides: dict):
    """Set each override that has no runner attribute on its module for the duration; restore after."""
    import contextlib

    @contextlib.contextmanager
    def held():
        saved = []
        try:
            for name, value in overrides.items():
                k = KNOBS[name]
                if k.runner_attr:
                    continue
                m = _SITE.fullmatch(k.sites[0])
                if m is None or "." in m["name"] or m["keys"] or m["param"]:
                    raise ValueError(f"{name}: only a module constant can be rebound, not {k.sites[0]}")
                module = importlib.import_module(m["rel"][:-3].replace("/", "."))
                saved.append((module, m["name"], getattr(module, m["name"])))
                setattr(module, m["name"], value)
            yield
        finally:
            for module, attr, old in reversed(saved):
                setattr(module, attr, old)
    return held()


def apply(runner, overrides: dict) -> None:
    """Set the overrides a runner carries as attributes."""
    for name, value in overrides.items():
        attr = KNOBS[name].runner_attr
        if attr and hasattr(runner, attr):
            setattr(runner, attr, value)
