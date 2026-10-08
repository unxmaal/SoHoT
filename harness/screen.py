"""Did it run at all? The rung between a ranked queue and a measurement.

Issue #148's ladder is sweep, inspect, rank, SCREEN, measure. The screen was
specified in #53 and never connected: `evals.run --screen` exists and stamps a
receipt tier, `screened` has been in the store's verdict vocabulary since the
store was built, and nothing has ever written one. So the queue this project
now ranks is ranked for a tier that cannot see it -- the third time in this
ladder that two correct halves had no rung between them.

WHAT A SCREEN ASKS is binary and cheap: did it run, did it emit an artifact.
That is the right question because it is how things have actually failed here
-- seedvr2 crashed 0/3, local-small never closed a tag 0/9, q3-14b returned
null content behind a passing rate. Almost nothing has failed by running and
scoring slightly worse.

IT NEVER DOWNLOADS. Fetching is its own explicit step (`lh fetch --run`) with
its own disk budget, and a tier that quietly pulls gigabytes because something
ranked well is how a laptop fills up overnight. A candidate whose weights are
absent is reported as waiting on a fetch, not screened and not failed.
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import NamedTuple

from harness import lanes, reasons

#: lane -> how to spell a candidate of that lane for evals.run, given a model
#: id. Empty means this harness has no way to invoke an arbitrary model in that
#: lane, which is a fact about the harness rather than about the candidate.
#:
#: The specs are the ones evals.run already parses; nothing new is invented
#: here, because a second spelling of the candidate language is the defect that
#: this project has filed twice under other names.
#: mlx_lm.server treats the request's `model` as a live repo id and swaps to
#: it, so a text candidate needs no prefix and no config entry. That is true of
#: every lane in lanes.TEXT_SERVED and only `code` was listed, so `web` and
#: `svg` -- the 3rd and 4th priorities -- reported `no-runner` for a candidate
#: the harness could in fact have screened. Issue #207.
#:
#: A LANE HOLDS MORE THAN ONE ENGINE, in preference order. It held exactly one
#: until 2026-09-21, and that single entry was doing the job of an adoption:
#: `mflux` was the image lane because it had been typed here, and since
#: mflux.ENTRY_POINTS is an enumerated table of families that no discovered
#: repo id is ever in, every challenger the loop found was refused before it
#: could be measured. The incumbent had never won anything. RULE #271's third
#: occurrence and the only one whose fix is not another per-lane patch.
#:
#: The order is INCUMBENT FIRST, which is a claim that measurement can settle
#: and currently has not: when both engines can run a model, the first one
#: listed gets it.
LANE_CANDIDATES = {
    "image": ("mflux:{model}", "diffusers:{model}"),
    # NOT `h3:{model}`. h3 reads one fixed checkpoint directory and takes no
    # repo id, so that spelling would have run MiniMax-H3 against every
    # discovered candidate and recorded the result under the candidate's name.
    # h3 is the lane's incumbent, spelled `h3` with nothing after it.
    "video": ("diffusers-video:{model}",),
    "music": ("acestep:{model}",),
    # A full model is a text candidate; a peft adapter goes to the engine its
    # card names (engines.adapter_engine): nimble or decider. #423, #467.
    "decide": ("{model}", "nimble:{model}", "decider:{model}"),
    # The OS reader is the incumbent, spelled `osocr:auto`; a discovered model is transformers. #562.
    "ocr": ("hf-ocr:{model}",),
    # bm25 is the incumbent; a cross-encoder first, an embedder when its card says so. #563.
    "retrieval": ("rerank:{model}", "embed:{model}"),
    # pii-regex is the incumbent; a discovered model is a transformers token tagger. #564.
    "pii": ("hf-pii:{model}",),
    # A GGUF instruct model on llama-server, which enforces the reply schema. #654.
    "claims": ("{model}",),
    "stt": ("stt:{model}",),
    "tts": ("tts:{model}",),
    **{lane: ("{model}",) for lane in lanes.TEXT_SERVED},
}

#: Why a row cannot be screened. Reported per row rather than filtered away: a
#: queue that silently drops what it cannot run looks like a queue that ran out.
WAITING, NO_RUNNER, READY = "waiting-on-fetch", "no-runner", "ready"


#: Words in a card that mean "this attaches to a model" rather than "this is
#: one". An adapter, a node pack or a workflow cannot be handed to a runner as
#: a candidate: mflux loads a base model, and `mflux:org/some-style-lora`
#: downloads gigabytes and then fails, recording a verdict that says nothing
#: about the thing.
NOT_A_MODEL = ("lora", "comfyui", "workflow", "adapter", "controlnet",
               "textual_inversion", "embedding",
               # A TOOL IS NOT A MODEL EITHER, and having a lane is not enough
               # to be one. PoopMan333/Video_Tools ranked SECOND in the whole
               # queue at 0.0 GiB, tagged `video, video-editing, image-editing,
               # gif, browser, offline`. It is a browser utility. The laneless
               # filter missed it because it HAS a lane, and the list above
               # missed it because it attaches to nothing. #249.
               "browser", "extension", "plugin", "gui", "toolkit",
               "cli-tool", "video-editing", "image-editing")

#: The one substring that is a model in its own right despite matching above.
#: Kept as an enumerated exception so the list can be read rather than guessed.
NOT_A_MODEL_EXCEPTIONS = ("lora-ready",
                          # A serving-compatibility tag on rerankers and embedders. #563.
                          "text-embeddings-inference")


def is_attachment(description: str) -> str:
    """The word that says this attaches to a model, or "" if none does.

    Read from the registry's own tags. A style LoRA and a ComfyUI node pack are
    both `text-to-image` and neither is something a lane can run alone.
    """
    text = (description or "").lower()
    for allowed in NOT_A_MODEL_EXCEPTIONS:
        text = text.replace(allowed, "")
    for word in NOT_A_MODEL:
        if word in text:
            return word
    return ""


#: Attachment kinds that are weights an adapter-loading engine can apply. A
#: ComfyUI pack or a browser tool is not, whatever lane it carries. #423.
ADAPTER_KINDS = ("lora", "adapter")


def takes_attachment(lane: str, kind: str) -> bool:
    """Whether some engine of `lane` loads an attachment of this kind onto
    its base, so it can be screened rather than dropped. #423."""
    if (kind or "").strip().lower() not in ADAPTER_KINDS:
        return False
    from harness import engines
    return any(engines.loads_adapters(s)
               for s in LANE_CANDIDATES.get(lanes.canonical(lane), ()))


#: A GGUF file served by llama-server's router, named by its stem. #295.
from harness.serving import LLAMACPP_PREFIX  # noqa: E402


def candidate_for(lane: str, model: str, attaches_to: str = "",
                  conn=None, card=None) -> str:
    """The best spelling of `model` for this lane, or "" when it has none.

    THE FIRST ENGINE THAT CAN ACTUALLY RUN IT WINS, not simply the first one
    listed. A lane with two engines whose first entry refuses most of what
    discovery finds would otherwise be a lane with one engine and a longer
    table.

    When NO engine takes it, the first spelling comes back anyway rather than
    "": the caller needs a spec to report the gap against, and `no_runner`
    holds the reason. "" is reserved for the two cases where there is nothing
    to spell at all -- no lane, or an attachment.

    ALREADY-SPELLED SPECS PASS THROUGH. A challenger arrives from the store as
    a bare repo id and is wrapped once; the INCUMBENT arrives from
    winners.typed() already spelled `mflux:flux2-klein-4b`, and wrapping it
    again produced `mflux:mflux:flux2-klein-4b`, which resolve() rejects. So
    the lane's own control contributed no cases, the challenger ran alone, and
    the run printed the pairing it intended above a receipt with one candidate
    in it. A candidate measured beside a control that did not run says nothing
    about the candidate. Issue #214.

    `attaches_to` is the stored word (proposals.attaches_to), never prose. #414.
    An adapter goes to the one engine its card (`card`, else the store's row
    via `conn`) identifies, and to none when nothing identifies it. #467.
    """
    specs = LANE_CANDIDATES.get(lanes.canonical(lane), ())
    from harness import ds4
    if model.startswith(ds4.PREFIX):
        return model
    if not attaches_to and lanes.canonical(lane) in lanes.GGUF_SERVED and ds4.recognised(model, card):
        # ds4's own GGUFs load in ds4-server and nowhere else. #611.
        return ds4.spec_for(model, (card or {}).get("siblings"), conn=conn)
    if attaches_to:
        if not takes_attachment(lane, attaches_to):
            return ""
        from harness import engines
        if card is None and conn is not None:
            from harness import memory_store as ms
            card = ms.card_of(conn, model)
        owner = engines.adapter_engine(model, card)
        specs = tuple(s for s in specs if engines.loads_adapters(s)
                      and s.partition(":")[0] == owner)
    if not specs:
        return ""
    if not attaches_to and len(specs) > 1:
        from harness import engines
        if card is None and conn is not None:
            from harness import memory_store as ms
            card = ms.card_of(conn, model)
        specs = engines.by_card(specs, card)
    if lanes.canonical(lane) == "svg":
        # OmniSVG runs only through its own runner, not a text server. #318.
        from evals.runners.omnisvg import MODELS
        for size, (_, repo) in MODELS.items():
            if model == repo:
                return f"omnisvg:{size}"
    if lanes.canonical(lane) in lanes.TEXT_SERVED:
        from harness import gguf
        stem = gguf.fetched(model, conn)
        if stem:
            return f"{LLAMACPP_PREFIX}{stem}"
    for spec in specs:
        prefix = spec.split("{model}", 1)[0]
        if prefix and model.startswith(prefix):
            return model
    from harness import engines
    if model.partition(",")[0].partition(":")[0] in engines.names():
        # Already a spec for some engine: video's default is bare `h3`, and
        # wrapping it made `diffusers-video:h3`. #343.
        return model
    built = [spec.format(model=model) for spec in specs]
    for spec in built:
        if not no_runner(spec):
            return spec
    return built[0]


def no_runner(spec: str) -> str:
    """Why nothing here can run `spec`, or "".

    A LANE HAVING A RUNNER IS NOT THE SAME QUESTION AS A RUNNER TAKING THIS
    MODEL. `candidate_for` only proved the lane has a spec template, so every
    discovered image candidate came back `ready`, was downloaded, and was then
    refused by evals.run for "no cases of a modality it can run" -- because
    engines.resolve raises on a model no mflux entry point serves,
    modality_of falls through to None, and a text candidate matches no image
    case. The refusal is correctly non-terminal (the harness failed, not the
    candidate), so the same candidate was re-fetched and re-screened on every
    sweep, forever, and the image lane could never screen anything the loop
    found. Asked here, before the disk is spent.
    """
    if not spec:
        return ""
    from harness import engines
    head, sep, _ = spec.partition(":")
    if not sep or head not in engines.names():
        # ONLY A PROCESS ENGINE CAN BE ASKED THIS. A text lane's candidate is
        # the bare repo id, which mlx_lm.server swaps to live, and `tts:`/
        # `stt:` are runner prefixes rather than engines. Asking resolve()
        # about those calls every ordinary code candidate unrunnable, which
        # is what the negative control in the end-to-end suite caught.
        return ""
    try:
        engines.resolve(spec)
    except ValueError as exc:
        return str(exc).split(". ", 1)[0]
    return ""


#: The eval cases the screen draws from.
CASES = Path(__file__).resolve().parent.parent / "evals" / "cases"


@functools.lru_cache(maxsize=4)
def _cases(root: str) -> tuple:
    from evals.core import load_cases
    return tuple(load_cases(root))


def case_gap(lane: str, spec: str) -> str:
    """Why no case in `lane` fits this candidate's method, or "". #555, RULE #219."""
    from evals.run import method_of
    lane = lanes.canonical(lane)
    mine = [c for c in _cases(str(CASES)) if c.modality == lane]
    method = method_of(spec)
    if not mine or any(not c.methods or method in c.methods for c in mine):
        return ""
    wants = ", ".join(f"{c.id} takes {'/'.join(c.methods)}" for c in mine)
    return f"no {lane} case fits the {method} method ({wants})"


def runner_gap(lane: str, model: str, attaches_to: str = "",
               conn=None, card=None) -> str:
    """Why no runner here takes this candidate, or "". `no_runner` asks of a
    spec; this also answers for an adapter no engine is known to load. #467."""
    spec = candidate_for(lane, model, attaches_to, conn=conn, card=card)
    from harness import ds4
    if spec.startswith(ds4.PREFIX):
        if lanes.canonical(lane) in ds4.NOT_SERVED:
            return ds4.NOT_SERVED[lanes.canonical(lane)]
        try:
            ds4.parse(spec)
        except ValueError as exc:
            return str(exc)
        return case_gap(lane, spec)
    if spec:
        from harness import engines
        if card is None and conn is not None:
            from harness import memory_store as ms
            card = ms.card_of(conn, model)
        return no_runner(spec) or case_gap(lane, spec) or engines.card_gap(spec, card)
    if attaches_to and takes_attachment(lane, attaches_to):
        from harness import engines
        return (f"no {lanes.canonical(lane)} engine is known to load this "
                f"{attaches_to}: its name, base model, library and tags name "
                f"none of {', '.join(sorted(engines.ADAPTER_ENGINES))}")
    return ""


def plan(rows, *, missing=None) -> list[dict]:
    """What a screen would do to each row, and what stands in the way.

    `missing` says what a candidate still needs that is not on disk -- ITSELF
    AND WHAT ITS CONFIG NAMES, because a complete repo is not a loadable model.
    Marvis-AI's 8-bit MLX repo is whole and names a tokenizer in a different
    repo; `ready` on that cost a real run to discover, and the screen tier
    exists to be cheap. Injected so this is testable without a cache and
    without a download. Issue #196.
    """
    if missing is None:
        from harness.fetching import missing as _missing
        missing = _missing
    out = []
    for row in rows:
        name = row["name"]
        lane = (row.get("lane") or "").strip().lower()
        attached = row.get("attaches_to") or ""
        spec = candidate_for(lane, name, attached, card=row)
        # A method downloads its base's weights, or none when its runner finds its own. #576.
        from harness import methods
        target = methods.weights_of(name) if methods.is_method(name) else name
        absent = [] if not spec or not target else missing(target)
        gap = runner_gap(lane, name, attached, card=row)
        if not spec or gap:
            state, why = NO_RUNNER, (
                gap if gap
                else f"a {attached}: it attaches to a model rather than being one, "
                f"so no runner takes it as a candidate" if attached
                else f"no runner for the {lane} lane" if lane
                else "no lane, so no case and no metric")
        elif absent == [target] and target != name:
            state, why = WAITING, (f"its base's weights, {target}, are not on disk; "
                                   f"soh fetch --run")
        elif absent == [name]:
            state, why = WAITING, "weights are not on disk; soh fetch --run"
        elif absent:
            # NAME WHAT IS MISSING. "not ready" without the id sends whoever
            # reads it back to the server log to find out what to fetch.
            state, why = WAITING, (
                f"needs {', '.join(absent)}, which its config names and "
                f"nothing has fetched; soh fetch --run")
        else:
            state, why = READY, f"evals.run --modality {lane} --screen"
        out.append({**row, "state": state, "why_not": why, "candidate": spec,
                    "modality": lane})
    return out


def gateway_routes(config=None) -> tuple[set[str], str]:
    """The alias names the gateway will accept, and the upstream behind them.

    LiteLLM validates the request's `model` against its configured aliases and
    answers HTTP 400 for anything else. mlx_lm.server, which sits behind it,
    treats the name as a live repo id and swaps to it. So a DISCOVERED text
    candidate -- which is always a repo id and never an alias -- has to reach
    the upstream directly or it is refused before a token is generated.
    """
    from harness import gateway

    data = gateway.load(config)
    names, base = set(), ""
    for entry in data.get("model_list") or []:
        if entry.get("model_name"):
            names.add(str(entry["model_name"]).strip().lower())
        base = base or (entry.get("litellm_params") or {}).get("api_base", "")
    return names, base


def upstream_of(alias: str, config=None) -> str:
    """The repo id an alias resolves to, or "" if it is not an alias.

    A PAIRED RUN HAS ONE GATEWAY AND TWO CANDIDATES. When the challenger is a
    repo id the whole run goes to mlx_lm.server, which has never heard of
    `q3-4b`, so the INCUMBENT then scores 0 of 27 and the run has no control.
    The config already maps every alias to the upstream behind it; the
    incumbent travels as that.

    `openai/` is LiteLLM's provider prefix, not part of the id.
    """
    from harness import gateway

    want = (alias or "").strip().lower()
    if not want:
        return ""
    for entry in gateway.load(config).get("model_list") or []:
        if str(entry.get("model_name", "")).strip().lower() != want:
            continue
        return gateway.strip_provider(
            str((entry.get("litellm_params") or {}).get("model", "")))
    return ""


def routed_gateway(model: str, config=None) -> str:
    """The `--gateway` value for this candidate, or "" for the default.

    An alias the gateway knows goes through the gateway. A repo id does not:
    it goes to the upstream that can hot-swap to it.

    RETURNS THE FORM `--gateway` WANTS. It used to return the config's own
    `.../v1` base and leave the caller to strip it, which argv() did and
    _measure_and_adopt did not: every request became /v1/v1/chat/completions
    and 404'd, so the measure scored BOTH candidates 0/27. A transform that
    only one of two callers performs is the same defect as two spellings of a
    name. #223.
    """
    from harness import methods
    model = methods.base_of(model) or model
    names, base = gateway_routes(config)
    if (model or "").strip().lower() in names:
        return ""
    from harness import gguf
    if gguf.fetched(model or "") or gguf.hub_stem(model or ""):
        return ""
    if "/" not in (model or ""):
        return ""
    return base.rsplit("/v1", 1)[0]


def argv(row: dict, outdir=None) -> list[str]:
    """The exact command a screen runs. One case, one repeat, no quality
    metrics: the screen answers whether it runs, and a metric here would invite
    ranking a screen against a measurement."""
    out = [sys.executable or "python", "-m", "evals.run",
           "--modality", row["modality"],
           "--screen", "--repeat", "1", "--candidates", row["candidate"]]
    upstream = routed_gateway(row.get("name") or "")
    if upstream:
        out += ["--gateway", upstream]
    if outdir:
        out += ["--out", str(outdir)]
    return out




class Verdict(NamedTuple):
    """A screen's verdict, with why as a column rather than a sentence. #408."""
    outcome: str
    detail: str
    reason: str
    until: str = ""
    failure_class: str = ""


def wrong_run(summary: dict | None, candidate: str, key: str = "") -> str:
    """Why this receipt is another candidate's, or "". #282."""
    if not summary or not candidate:
        return ""
    if row_for(summary, candidate, key) is not None:
        return ""
    return (f"the receipt names {', '.join(sorted(summary))} rather than "
            f"{candidate}, so it is not this run's")


def row_for(summary: dict | None, candidate: str,
            key: str = "") -> dict | None:
    """This candidate's summary row, under the key its runner wrote. #407."""
    if not summary:
        return None
    if not key:
        from harness import candidates
        key = candidates.key_of(candidate)
    return (summary[key] or {}) if key and key in summary else None


def why_nothing_passed(summary: dict | None, candidate: str,
                       key: str = "") -> str:
    """The checker's own reason for failing, or "". #281."""
    rows = row_for(summary, candidate, key) or {}
    failures = [str(f) for f in (rows.get("failures") or []) if f]
    return "; ".join(failures)[:300]


#: The package whose version decides what a process engine can load. #385.
ENGINE_RUNTIMES = {"mflux": "mflux", "diffusers": "diffusers",
                   "diffusers-video": "diffusers", "acestep": "ace-step",
                   # The audio server's runtime, as scripts/versions.sh pins it. #408.
                   "tts": "mlx-audio", "stt": "mlx-audio",
                   "hf-ocr": "transformers", "rerank": "sentence-transformers",
                   "embed": "sentence-transformers", "hf-pii": "transformers",
                   # Its checkout's commit date, which machine.versions records. #611.
                   "ds4": "ds4"}
LOAD_RUNTIME = "mlx-lm"


def engine_runtime(candidate: str) -> str:
    head = candidate.partition(",")[0].partition(":")[0].strip()
    return ENGINE_RUNTIMES.get(head, "")


def _installed(pkg: str) -> str:
    """The recorded version of pkg on this machine, "0" when absent. #415."""
    from harness import memory_store as ms
    return ms.this_machine().get("versions", {}).get(pkg) or "0"


def load_until(candidate: str = "") -> str:
    """The predicate that reopens a load failure: a newer runtime."""
    if candidate.startswith(LLAMACPP_PREFIX):
        return f"version:llama.cpp>{_installed('llama.cpp')}"
    runtime = engine_runtime(candidate)
    if runtime:
        return f"version:{runtime}>{_installed(runtime)}"
    return f"version:{LOAD_RUNTIME}>{_installed(LOAD_RUNTIME)}"


def _sentence(cls: str, why: str, limit: str) -> str:
    tail = f": {why}" if why else ""
    if cls == reasons.LOAD_FAILED_RUNTIME:
        return f"the installed runtime could not load it{tail}"
    if cls == reasons.LOAD_FAILED_LAYOUT:
        return f"needs its own runner: the stock loader could not assemble it{tail}"
    if cls == reasons.GPU_FAULT:
        return f"the GPU faulted running it on this machine{tail}"
    if cls == reasons.BACKEND_FAULT:
        return f"the MPS backend aborted running it{tail}"
    if reasons.CLASSES[cls][1] == reasons.LIMIT:
        return (f"stopped at a limit this harness chose"
                f"{f' ({limit})' if limit else ''}{tail}")
    if reasons.CLASSES[cls][1] == reasons.HARNESS:
        return (f"not screened: {cls}. The harness could not deliver the "
                f"request, which says nothing about the candidate{tail}")
    return f"it ran and passed nothing{tail}"


def decide_class(cls: str, why: str = "", candidate: str = "",
                 limits=(), facts: dict | None = None) -> Verdict:
    """The verdict a failure class means, with its reason and until. #408."""
    got, reason = reasons.CLASSES[cls]
    limit = sorted(limits)[0] if limits else ""
    until = ""
    if reason == reasons.RUNTIME:
        until = load_until(candidate)
    elif reason == reasons.LIMIT and limit:
        until = f"limit:{limit}"
    elif cls == reasons.GPU_FAULT and (facts or {}).get("memory_gb"):
        until = f"memory_gb:>{float(facts['memory_gb']):.0f}"
    return Verdict(got, _sentence(cls, why, limit), reason, until, cls)


def outcome(returncode: int, summary: dict | None, candidate: str = "",
            key: str = "", stderr_class: str = "",
            facts: dict | None = None) -> Verdict:
    """A store verdict from one screen run, decided from failure classes.

    `broken` is TERMINAL and `screened` is not. A request the harness could
    not deliver is `queued`; a limit the harness chose, a runtime gap and a
    GPU fault are `declined` with an `until` that reopens them.
    `stderr_class` is the run's own stderr, classed once by the caller, and
    only counts when the run wrote no receipt.
    """
    if summary is None and stderr_class:
        return decide_class(stderr_class, candidate=candidate, facts=facts)
    mismatch = wrong_run(summary, candidate, key) if candidate else ""
    if mismatch:
        return Verdict("queued", f"not screened: {mismatch}", reasons.HARNESS)
    if returncode != 0:
        return Verdict("broken", f"the screen exited {returncode}",
                       reasons.CANDIDATE, failure_class=reasons.CRASHED)
    if not summary:
        return Verdict("broken", "the screen produced no rows",
                       reasons.CANDIDATE, failure_class=reasons.CRASHED)
    # THE SUMMARY SPELLS IT `passed`; reading `pass` recorded every pass broken.
    rows = sum(int(v.get("passed", 0)) for v in summary.values())
    if rows:
        return Verdict("screened", f"{rows} case(s) passed a screen",
                       reasons.CANDIDATE)
    mine = ([row_for(summary, candidate, key) or {}] if candidate
            else list(summary.values()))
    cls = reasons.first(c for r in mine for c in (r.get("failure_classes") or {}))
    why = why_nothing_passed(summary, candidate, key) if candidate else ""
    limits = [lim for r in mine for lim in (r.get("limits") or [])]
    return decide_class(cls or reasons.CONTENT_FAILED, why, candidate,
                        limits, facts)
